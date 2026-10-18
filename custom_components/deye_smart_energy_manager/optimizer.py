"""Hourly energy planner (SHADOW engine).

Deterministic, dependency-free heuristic v1. It produces a feasible
hourly plan — charge PV surplus, grid-charge in cheap hours when an
expensive deficit is coming, discharge only into expensive deficits —
with an explainable reason per slot. It is structured so a HiGHS LP can
later replace ``optimize()`` without touching inputs/outputs (see
docs/OPTIMIZATION.md).

Conventions (same as EnergySnapshot):
  battery_power_w  < 0 charging / > 0 discharging (AC side, W)
  grid_power_w     > 0 import  / < 0 export
  Energy amounts are AC-side kWh per hourly slot.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import (
    ACTION_CHARGE_GRID,
    ACTION_CHARGE_PV,
    ACTION_DISCHARGE,
    ACTION_EXPORT,
    ACTION_HOLD,
    ACTION_IDLE,
    ACTION_IMPORT,
    EnergyPlan,
    PlanSlot,
)

_LOGGER = logging.getLogger(__name__)

_UNKNOWN = -1.0  # internal sentinel for missing prices


@dataclass(frozen=True)
class BatteryParams:
    """Battery constraints, in AC-side terms."""

    usable_kwh: float
    soc_pct: float                 # current SOC
    soc_min_pct: float
    soc_max_pct: float
    reserve_pct: float             # never discharge below this
    max_charge_w: float
    max_discharge_w: float
    charge_efficiency: float       # AC -> stored
    discharge_efficiency: float    # stored -> AC
    degradation_eur_kwh: float


@dataclass(frozen=True)
class PlannerInput:
    """Aligned hourly series consumed by ``optimize``."""

    first_hour: datetime
    import_prices: tuple[float | None, ...]  # EUR/kWh per hour
    export_price_eur_kwh: float              # flat fallback
    pv_kw: tuple[float, ...]
    load_kw: tuple[float, ...]
    battery: BatteryParams
    export_prices: tuple[float | None, ...] | None = None  # hourly, wins


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Nearest-rank quantile without numpy."""
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def optimize(inp: PlannerInput) -> EnergyPlan:
    """Build a feasible hourly plan. Pure; never raises on bad data."""
    n = len(inp.import_prices)
    warnings: list[str] = []

    prices = list(inp.import_prices)
    known = sorted(p for p in prices if p is not None)
    if not known:
        warnings.append("no_price_data")
        prices = [_UNKNOWN] * n
    elif any(p is None for p in prices):
        warnings.append("price_gaps_filled")
        fill = statistics.median(known)
        prices = [fill if p is None else p for p in prices]

    bat = inp.battery
    warnings.extend(_battery_warnings(bat))

    if known:
        cheap_thr = _quantile(known, 0.25)
        # Round-trip arbitrage is only worthwhile above the efficiency/
        # degradation floor, and "expensive" must beat "cheap" strictly —
        # otherwise flat price curves would trigger pointless cycling.
        floor = known[0] / (bat.charge_efficiency * bat.discharge_efficiency) \
            + bat.degradation_eur_kwh
        exp_thr = max(_quantile(known, 0.75), floor, cheap_thr + 0.005)
    else:
        cheap_thr = exp_thr = float("inf")  # never charge/discharge on price

    soc_kwh = bat.usable_kwh * _clip_soc(bat.soc_pct, bat.soc_min_pct) / 100.0
    cap_min = bat.usable_kwh * bat.soc_min_pct / 100.0
    cap_max = bat.usable_kwh * bat.soc_max_pct / 100.0
    cap_res = bat.usable_kwh * bat.reserve_pct / 100.0

    # Pre-compute, for each hour, the remaining expensive-deficit energy
    # (AC kWh) still ahead — bounds grid charging to real need.
    fut_deficit = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        deficit = max(0.0, inp.load_kw[i] - inp.pv_kw[i])
        price = prices[i]
        add = deficit if price >= exp_thr else 0.0
        fut_deficit[i] = fut_deficit[i + 1] + add

    slots: list[PlanSlot] = []
    cost = baseline = 0.0
    for i in range(n):
        pv = inp.pv_kw[i] if i < len(inp.pv_kw) else 0.0
        load = inp.load_kw[i] if i < len(inp.load_kw) else 0.0
        price = prices[i] if prices[i] != _UNKNOWN else None
        eprice = inp.export_price_eur_kwh
        if inp.export_prices and i < len(inp.export_prices) \
                and inp.export_prices[i] is not None:
            eprice = inp.export_prices[i]
        hour = inp.first_hour + timedelta(hours=i)

        baseline += max(0.0, load - pv) * (price or 0.0)
        baseline -= max(0.0, pv - load) * eprice

        batt_w = 0.0  # signed convention: - charge / + discharge
        reason = "balanced"
        action = ACTION_IDLE
        surplus = pv - load

        if surplus > 0.0:
            # Store PV surplus first, export the remainder.
            headroom = max(0.0, cap_max - soc_kwh) / bat.charge_efficiency
            chg = min(surplus, bat.max_charge_w / 1000.0, headroom)
            soc_kwh += chg * bat.charge_efficiency
            batt_w = -chg * 1000.0
            grid = chg - surplus  # residual surplus exported (negative)
            action = ACTION_CHARGE_PV if chg > 0 else ACTION_EXPORT
            reason = "pv_surplus" if chg > 0 else "pv_surplus_battery_full"
        else:
            deficit = -surplus
            if price is not None and price <= cheap_thr and \
                    fut_deficit[i + 1] > 0:
                # Cheap hour with expensive deficits ahead: cover the
                # deficit from grid AND pre-charge toward the need.
                headroom = max(
                    0.0,
                    min(cap_max,
                        cap_res + fut_deficit[i + 1] / bat.discharge_efficiency)
                    - soc_kwh,
                ) / bat.charge_efficiency
                chg = min(bat.max_charge_w / 1000.0, headroom)
                if chg > 0.01:
                    soc_kwh += chg * bat.charge_efficiency
                    batt_w = -chg * 1000.0
                    action = ACTION_CHARGE_GRID
                    reason = "cheap_hour_precharge"
                else:
                    action = ACTION_IMPORT
                    reason = "cheap_hour_no_headroom"
                grid = deficit + chg
            elif price is not None and price >= exp_thr and soc_kwh > cap_res:
                # Expensive deficit: discharge above the reserve.
                avail = (soc_kwh - cap_res) * bat.discharge_efficiency
                dis = min(deficit, bat.max_discharge_w / 1000.0, avail)
                soc_kwh -= dis / bat.discharge_efficiency
                batt_w = dis * 1000.0
                grid = deficit - dis
                action = ACTION_DISCHARGE
                reason = "expensive_deficit"
            else:
                grid = deficit
                if deficit <= 0.0:
                    reason = "balanced"
                elif price is not None and price >= exp_thr:
                    action = ACTION_HOLD
                    reason = "reserve_hold"
                else:
                    action = ACTION_IMPORT
                    reason = "mid_price_import"

        imp = max(0.0, grid)
        exp = max(0.0, -grid)
        cost += imp * (price or 0.0)
        cost -= exp * eprice

        slots.append(
            PlanSlot(
                start=hour,
                action=action,
                battery_power_w=round(batt_w, 1),
                grid_power_w=round(grid * 1000.0, 1),
                soc_end_pct=round(100.0 * soc_kwh / bat.usable_kwh, 1)
                if bat.usable_kwh else 0.0,
                import_price_eur_kwh=price,
                reason=reason,
            )
        )

    return EnergyPlan(
        generated_at=inp.first_hour,
        horizon_hours=n,
        slots=tuple(slots),
        expected_cost_eur=round(cost, 4),
        baseline_cost_eur=round(baseline, 4),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _clip_soc(soc: float, floor: float) -> float:
    return max(floor, min(100.0, soc))


def _battery_warnings(bat: BatteryParams) -> list[str]:
    out: list[str] = []
    if bat.usable_kwh <= 0:
        out.append("battery_capacity_unknown")
    if bat.soc_min_pct >= bat.soc_max_pct:
        out.append("invalid_soc_range")
    if bat.reserve_pct < bat.soc_min_pct:
        out.append("reserve_below_min")
    return out
