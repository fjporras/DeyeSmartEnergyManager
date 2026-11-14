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
    auto_floor_pct: float = 15.0    # physical cutoff for autonomous discharge


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
    soc_target_pct: float | None = None   # target_soc mode constraint
    target_idx: int | None = None         # slot that must end >= target


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
    cap_floor = bat.usable_kwh * bat.auto_floor_pct / 100.0

    # --- SOC-target constraint (mode target_soc) -------------------------
    # The plan must end slot ``target_idx`` at >= ``soc_target_pct``.
    # ``tneed`` is the stored kWh still missing after expected PV
    # coverage, i.e. what grid charging in cheap hours must still acquire.
    target_stored: float | None = None
    tneed = 0.0
    pv_suf = [0.0] * (n + 1)
    target_idx = inp.target_idx if inp.soc_target_pct is not None else None
    if target_idx is not None and 0 <= target_idx < n:
        target_stored = (
            bat.usable_kwh * min(100.0, max(0.0, inp.soc_target_pct)) / 100.0
        )
        if target_stored > cap_max:
            warnings.append("soc_target_above_soc_max")
            target_stored = cap_max
        max_chg_kw = bat.max_charge_w / 1000.0
        pv_st = [0.0] * n
        for j in range(target_idx + 1):
            pv = inp.pv_kw[j] if j < len(inp.pv_kw) else 0.0
            load = inp.load_kw[j] if j < len(inp.load_kw) else 0.0
            pv_st[j] = (
                min(max(0.0, pv - load), max_chg_kw) * bat.charge_efficiency
            )
        pv_suf = [0.0] * (n + 1)
        for j in range(target_idx, -1, -1):
            pv_suf[j] = pv_suf[j + 1] + pv_st[j]
        tneed = max(0.0, target_stored - soc_kwh - pv_suf[0])
    soc_at_target: float | None = None

    # Pre-compute, for each hour, the remaining expensive-deficit energy
    # (AC kWh) still ahead — bounds grid charging to real need.
    fut_deficit = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        deficit = max(0.0, inp.load_kw[i] - inp.pv_kw[i])
        price = prices[i]
        add = deficit if price >= exp_thr else 0.0
        fut_deficit[i] = fut_deficit[i + 1] + add

    # --- Autonomous-discharge reserve floor ------------------------------
    # The inverter drains the battery for EVERY deficit hour (load - PV)
    # down to its physical cutoff — it does not consult prices and there
    # is no discharge switch. ``req_end[i]`` is the minimum stored kWh
    # required at the end of hour i so the trajectory never breaches the
    # reserve floor under that physics. Backward pass over net stored
    # drain, crediting each deficit hour's grid-charge capacity (the
    # forward pass really does charge when the floor demands it).
    max_dis_ac = bat.max_discharge_w / 1000.0
    max_chg_ac = bat.max_charge_w / 1000.0
    rate = max_chg_ac * bat.charge_efficiency  # stored kWh per hour
    net_st = [0.0] * n
    charge_cap_st = [0.0] * n
    auto_st = [0.0] * n
    for j in range(n):
        pv_j = inp.pv_kw[j] if j < len(inp.pv_kw) else 0.0
        load_j = inp.load_kw[j] if j < len(inp.load_kw) else 0.0
        deficit_j = max(0.0, load_j - pv_j)
        surplus_j = max(0.0, pv_j - load_j)
        dis_st = min(deficit_j, max_dis_ac) / bat.discharge_efficiency
        pv_st_j = min(surplus_j, max_chg_ac) * bat.charge_efficiency
        net_st[j] = dis_st - pv_st_j
        auto_st[j] = dis_st
        if deficit_j > 0.0:
            charge_cap_st[j] = rate
    need_end = [cap_res] * n
    run = cap_res
    for i in range(n - 1, 0, -1):
        run = max(cap_res, min(cap_max, run + net_st[i] - charge_cap_st[i]))
        need_end[i - 1] = run

    # SOC-target trajectory floor: same recurrence anchored at
    # ``target_stored`` for the end of ``target_idx``. ``req_end`` is the
    # element-wise maximum of both floors.
    req_end = list(need_end)
    if target_stored is not None and target_idx is not None \
            and 0 <= target_idx < n:
        t_run = max(cap_res, target_stored)
        req_end[target_idx] = max(req_end[target_idx], t_run)
        for i in range(target_idx, 0, -1):
            t_run = max(
                cap_res,
                min(cap_max, t_run + net_st[i] - charge_cap_st[i]),
            )
            req_end[i - 1] = max(req_end[i - 1], t_run)

    # Stored kWh the battery auto-discharges from hour i through the
    # target hour — makes ``tneed`` drain-aware.
    drain_suf = [0.0] * (n + 1)
    for j in range(n - 1, -1, -1):
        drain_suf[j] = drain_suf[j + 1] + auto_st[j]
    target_drain = (
        drain_suf[target_idx + 1] if target_idx is not None else 0.0
    )

    slots: list[PlanSlot] = []
    cost = baseline = 0.0
    reserve_breach = False
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

        # Recompute the remaining SOC-target need every hour: a discharge
        # after an early fill re-opens the need, so it cannot be a
        # one-shot decrement. ``drain_suf`` adds the autonomous discharge
        # expected between now and the target hour.
        if target_stored is not None and i <= target_idx:
            tneed = max(
                0.0,
                target_stored
                - soc_kwh
                + (drain_suf[i] - target_drain)
                - pv_suf[i],
            )

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
            want_target = (
                target_stored is not None
                and i <= target_idx
                and tneed > 0.01
            )
            cheap_ok = (
                price is not None
                and price <= cheap_thr
                and (fut_deficit[i + 1] > 0 or want_target)
            )
            # Forced target charge: buy now only the stored energy that
            # strictly-cheaper deficit hours before the deadline cannot
            # deliver. This schedules grid charging into the cheapest
            # available hours even when they are above the P25 threshold.
            forced_chg = 0.0
            if want_target and price is not None and not cheap_ok:
                cheaper_cap = 0.0
                for j in range(i + 1, target_idx + 1):
                    pj = prices[j] if j < len(prices) else None
                    if pj is None or pj == _UNKNOWN or pj >= price:
                        continue
                    pv_j = inp.pv_kw[j] if j < len(inp.pv_kw) else 0.0
                    load_j = inp.load_kw[j] if j < len(inp.load_kw) else 0.0
                    if pv_j - load_j <= 0.0:
                        cheaper_cap += rate
                if tneed > cheaper_cap:
                    forced_chg = (tneed - cheaper_cap) / bat.charge_efficiency

            # Physics: the inverter covers the deficit from the battery
            # down to its physical cutoff — prices are irrelevant to it.
            # Only a grid-charge slot lets the grid serve the deficit
            # instead. ``dis_auto`` is what the battery WOULD discharge.
            dis_auto = min(
                deficit,
                max_dis_ac,
                max(0.0, soc_kwh - cap_floor) * bat.discharge_efficiency,
            )
            soc_after_auto = soc_kwh - dis_auto / bat.discharge_efficiency

            econ_active = cheap_ok or forced_chg > 0.0
            want_stored = cap_res
            if cheap_ok:
                want_stored = max(
                    want_stored,
                    cap_res
                    + fut_deficit[i + 1] / bat.discharge_efficiency,
                )
                if want_target:
                    want_stored = max(want_stored, soc_kwh + tneed)
            elif forced_chg > 0.0:
                want_stored = max(
                    want_stored,
                    soc_kwh + forced_chg * bat.charge_efficiency,
                )
            # Any charge also tops the trajectory up to the floor.
            want_stored = max(want_stored, req_end[i])
            headroom_ac = max(0.0, cap_max - soc_kwh) \
                / bat.charge_efficiency
            econ_chg = 0.0
            if econ_active:
                econ_chg = min(
                    max_chg_ac,
                    max(
                        0.0,
                        (min(cap_max, want_stored) - soc_kwh)
                        / bat.charge_efficiency,
                    ),
                    headroom_ac,
                )
                if want_target and cheap_ok:
                    econ_chg = min(econ_chg, tneed / bat.charge_efficiency)
                elif forced_chg > 0.0:
                    econ_chg = min(econ_chg, forced_chg)
            # Reserve/target guard: if autonomous discharge would breach
            # the required floor, charge now — any amount flips the
            # deficit coverage to the grid. When the floor is pinned at
            # ``cap_max`` by an infeasible reserve trajectory (and no
            # SOC target justifies it), charging cannot help: let the
            # battery discharge to its physical floor and warn instead.
            target_binds = (
                target_stored is not None
                and i <= target_idx
                and req_end[i] > need_end[i] + 1e-6
            )
            floor_infeasible = (
                req_end[i] >= cap_max - 1e-6 and not target_binds
            )
            guard_breach = (
                not floor_infeasible
                and soc_after_auto < req_end[i] - 1e-6
            )
            guard_chg = 0.0
            if guard_breach:
                guard_chg = max(
                    0.05,
                    (req_end[i] - soc_kwh) / bat.charge_efficiency,
                )
            chg = min(max_chg_ac, headroom_ac, max(econ_chg, guard_chg))
            if chg <= 0.01 and guard_chg > 0.0:
                # No headroom but coverage must flip to the grid anyway
                # (e.g. full battery on the target hour).
                chg = 0.05
            if chg > 0.01 and (econ_active or guard_chg > 0.0):
                soc_kwh = min(
                    cap_max, soc_kwh + chg * bat.charge_efficiency
                )
                batt_w = -chg * 1000.0
                action = ACTION_CHARGE_GRID
                if want_target and cheap_ok \
                        and fut_deficit[i + 1] <= 0.0:
                    reason = "soc_target_precharge"
                elif (forced_chg > 0.0 and not cheap_ok) \
                        or (guard_breach and target_binds):
                    reason = "soc_target_forced_charge"
                elif guard_chg > econ_chg or not econ_active:
                    reason = "soc_reserve_charge"
                else:
                    reason = "cheap_hour_precharge"
                grid = deficit + chg
            else:
                # No charge slot: the battery discharges autonomously and
                # the grid covers only what the battery cannot.
                soc_kwh = soc_after_auto
                grid = deficit - dis_auto
                if dis_auto > 0.01:
                    batt_w = dis_auto * 1000.0
                    action = ACTION_DISCHARGE
                    reason = "auto_discharge"
                else:
                    action = ACTION_IMPORT
                    reason = "mid_price_import"

        if target_idx is not None and i == target_idx:
            soc_at_target = soc_kwh
        if soc_kwh < req_end[i] - 0.05:
            reserve_breach = True
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

    if target_stored is not None and soc_at_target is not None \
            and soc_at_target < target_stored - 1e-6:
        warnings.append("soc_target_not_reached")
    if reserve_breach:
        warnings.append("soc_reserve_risk")

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
