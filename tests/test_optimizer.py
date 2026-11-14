"""Unit tests for the heuristic hourly planner."""
from __future__ import annotations

from datetime import datetime, timedelta

from dsem import model
from dsem.optimizer import BatteryParams, PlannerInput, optimize

T0 = datetime(2026, 10, 18, 0, 0)

BAT = BatteryParams(
    usable_kwh=30.0,
    soc_pct=50.0,
    soc_min_pct=20.0,
    soc_max_pct=95.0,
    reserve_pct=35.0,
    max_charge_w=5300.0,
    max_discharge_w=6300.0,
    charge_efficiency=0.95,
    discharge_efficiency=0.95,
    degradation_eur_kwh=0.02,
)


def _inp(prices, pv, load, bat=BAT):
    n = len(prices)
    return PlannerInput(
        first_hour=T0,
        import_prices=tuple(prices),
        export_price_eur_kwh=0.14,
        pv_kw=tuple(pv),
        load_kw=tuple(load),
        battery=bat,
    )


def _arbitrage_prices(n=24):
    # Cheap 02-05 (0.05), mid 0.15, expensive 19-22 (0.30).
    return [
        0.05 if 2 <= h <= 5 else 0.30 if 19 <= h <= 22 else 0.15
        for h in range(n)
    ]


def test_arbitrage_charges_cheap_and_discharges_expensive():
    prices = _arbitrage_prices()
    plan = optimize(_inp(prices, [0.0] * 24, [2.0] * 24))
    grid_charged = [
        s.start.hour for s in plan.slots
        if s.action == model.ACTION_CHARGE_GRID
    ]
    # Grid charging only happens while the price is below the expensive
    # block (cheap precharge, mid-price top-ups and reserve guard).
    assert grid_charged and all(prices[h] < 0.30 for h in grid_charged)
    # The battery autonomously serves every deficit hour; during the
    # expensive block it covers the load entirely (no grid import).
    expensive = [s for s in plan.slots if 19 <= s.start.hour <= 22]
    assert expensive and all(
        s.grid_power_w < 1.0 and s.battery_power_w > 0
        for s in expensive
    )
    assert plan.expected_cost_eur < plan.baseline_cost_eur
    assert plan.expected_savings_eur > 0


def test_soc_bounds_and_reserve_respected():
    prices = _arbitrage_prices()
    plan = optimize(_inp(prices, [0.0] * 24, [5.0] * 24))
    for slot in plan.slots:
        assert 35.0 - 0.2 <= slot.soc_end_pct <= 95.0 + 0.2
        assert abs(slot.battery_power_w) <= 6300.0 + 1


def test_pv_surplus_charges_battery_first():
    pv = [8.0 if 10 <= h <= 15 else 0.0 for h in range(24)]
    plan = optimize(_inp([0.15] * 24, pv, [2.0] * 24))
    midday = [s for s in plan.slots if 10 <= s.start.hour <= 15]
    assert any(s.action == model.ACTION_CHARGE_PV for s in midday)
    # Surplus beyond charge limit / capacity is exported (grid < 0).
    assert any(s.grid_power_w < 0 for s in midday)


def test_flat_prices_no_arbitrage():
    """Flat prices: no economic cycling — the battery only holds the
    reserve floor via autonomous discharge + epsilon grid cover."""
    plan = optimize(_inp([0.15] * 24, [0.0] * 24, [2.0] * 24))
    assert not any(
        s.reason in (
            "cheap_hour_precharge",
            "soc_target_precharge",
            "soc_target_forced_charge",
        )
        for s in plan.slots
    )
    # Reserve floor is never breached.
    assert all(s.soc_end_pct >= 35.0 - 0.2 for s in plan.slots)


def test_missing_prices_disable_arbitrage():
    plan = optimize(
        _inp([None] * 24, [0.0] * 24, [2.0] * 24)
    )
    assert "no_price_data" in plan.warnings
    # Without prices there is no economic charging — only the reserve
    # guard may flip deficit coverage to the grid.
    assert all(
        s.reason == "soc_reserve_charge"
        for s in plan.slots
        if s.action == model.ACTION_CHARGE_GRID
    )
    assert all(s.soc_end_pct >= 35.0 - 0.2 for s in plan.slots)


def test_reserve_blocks_discharge_when_soc_low():
    bat = BatteryParams(
        **{**BAT.__dict__, "soc_pct": 36.0}  # just above reserve 35
    )
    plan = optimize(_inp(_arbitrage_prices(), [0.0] * 24, [2.0] * 24,
                         bat=bat))
    for slot in plan.slots:
        if slot.action == model.ACTION_DISCHARGE:
            assert slot.soc_end_pct >= 35.0 - 0.2


def test_full_battery_exports_surplus():
    bat = BatteryParams(**{**BAT.__dict__, "soc_pct": 95.0})
    pv = [6.0 if 10 <= h <= 13 else 0.0 for h in range(24)]
    # Zero load: no deficit hours, so the full battery is never drained
    # and the midday surplus must be exported.
    plan = optimize(_inp([0.15] * 24, pv, [0.0] * 24, bat=bat))
    midday = [s for s in plan.slots if 10 <= s.start.hour <= 13]
    assert all(s.grid_power_w < 0 for s in midday)


def test_autonomous_discharge_down_to_physical_floor():
    """With reserve below the physical cutoff, the battery drains to
    ``auto_floor_pct`` and the grid covers the rest — prices ignored."""
    bat = BatteryParams(
        **{**BAT.__dict__, "soc_pct": 20.0, "reserve_pct": 10.0}
    )
    # 8 kW load exceeds max discharge (6.3 kW): battery drains to the
    # 15% floor, then plain imports cover the remainder.
    plan = optimize(_inp([0.15] * 24, [0.0] * 24, [8.0] * 24, bat=bat))
    floor_pct = 100.0 * bat.usable_kwh * bat.auto_floor_pct / 100.0 \
        / bat.usable_kwh
    assert all(s.soc_end_pct >= floor_pct - 0.2 for s in plan.slots)
    assert any(
        s.action == model.ACTION_IMPORT and s.battery_power_w == 0
        for s in plan.slots
    )


def test_reserve_guard_forces_charge_at_any_price():
    """When autonomous discharge would breach the reserve, the plan
    grid-charges even at mid prices (``soc_reserve_charge``)."""
    plan = optimize(_inp([0.15] * 24, [0.0] * 24, [2.0] * 24))
    guarded = [
        s for s in plan.slots if s.reason == "soc_reserve_charge"
    ]
    assert guarded
    assert all(s.action == model.ACTION_CHARGE_GRID for s in guarded)


def test_soc_reserve_risk_warns_when_infeasible():
    """Reserve above what charge capacity can sustain -> warning."""
    bat = BatteryParams(**{**BAT.__dict__, "reserve_pct": 80.0})
    plan = optimize(_inp([0.15] * 24, [0.0] * 24, [8.0] * 24, bat=bat))
    assert "soc_reserve_risk" in plan.warnings


def test_invalid_battery_params_warn():
    bat = BatteryParams(**{**BAT.__dict__, "soc_min_pct": 96.0})
    plan = optimize(_inp([0.15] * 24, [0.0] * 24, [1.0] * 24, bat=bat))
    assert "invalid_soc_range" in plan.warnings


def test_hourly_export_prices_applied():
    """Hourly export series (InfluxDB vertido) overrides the flat price."""
    bat = BatteryParams(**{**BAT.__dict__, "soc_pct": 95.0})
    pv = [6.0 if h == 12 else 0.0 for h in range(24)]
    inp = PlannerInput(
        first_hour=T0,
        import_prices=tuple([0.15] * 24),
        export_price_eur_kwh=0.14,
        pv_kw=tuple(pv),
        load_kw=tuple([1.0] * 24),
        battery=bat,
        export_prices=tuple(
            0.05 if h == 12 else 0.14 for h in range(24)
        ),
    )
    plan = optimize(PlannerInput(
        **{**inp.__dict__, "load_kw": tuple([0.0] * 24)}
    ))
    slot12 = plan.slots[12]
    assert slot12.grid_power_w < 0  # exporting
    # 6 kW exported at the hourly vertido price 0.05 — not the flat
    # 0.14 fallback (which would give -0.84).
    assert abs(plan.expected_cost_eur - (-6.0 * 0.05)) < 0.01


def _target_input(target_idx, soc_target, prices=None, pv=None, load=None):
    inp = _inp(
        prices or _arbitrage_prices(),
        pv if pv is not None else [0.0] * 24,
        load if load is not None else [2.0] * 24,
    )
    return PlannerInput(
        **{**inp.__dict__, "soc_target_pct": soc_target,
           "target_idx": target_idx}
    )


def test_soc_target_reached_via_cheap_precharge():
    """80% by hour 8: cheap/mid hours before it must pre-charge."""
    plan = optimize(_target_input(8, 80.0))
    slot8 = plan.slots[8]
    assert slot8.soc_end_pct >= 79.5
    assert "soc_target_not_reached" not in plan.warnings
    # Some grid charging happened before the target hour.
    assert any(
        s.action == model.ACTION_CHARGE_GRID and s.start.hour < 8
        for s in plan.slots
    )


def test_soc_target_blocks_discharge_below_trajectory():
    """An expensive hour before the target cannot drain below the floor."""
    # Expensive spike at hour 6, target at hour 8 — floor must hold.
    prices = [0.05 if h in (2, 3, 4) else 0.10 for h in range(24)]
    prices[6] = 0.40
    plan = optimize(_target_input(8, 85.0, prices=prices))
    slot8 = plan.slots[8]
    assert slot8.soc_end_pct >= 84.5
    assert "soc_target_not_reached" not in plan.warnings


def test_soc_target_unreachable_warns():
    """Flat mid prices + tiny window -> target cannot be met: warn."""
    plan = optimize(
        _target_input(1, 95.0, prices=[0.20] * 24)
    )
    assert "soc_target_not_reached" in plan.warnings


def test_soc_target_uses_pv_surplus():
    """PV surplus before the target counts toward it (no grid needed)."""
    pv = [9.0 if 10 <= h <= 15 else 0.0 for h in range(24)]
    plan = optimize(_target_input(16, 90.0, pv=pv))
    assert plan.slots[16].soc_end_pct >= 89.5
    assert "soc_target_not_reached" not in plan.warnings


def test_soc_target_forces_charge_at_mid_prices():
    """When cheap hours cannot cover the target, mid-price hours before
    the deadline must grid-charge the shortfall — cheapest first."""
    # Cheap hours 0-1 and 8-14 keep the global P25 at 0.05, but before
    # the hour-7 deadline only two cheap hours exist; mid-price hours
    # 2-6 must cover the shortfall via forced charging.
    prices = (
        [0.05, 0.05] + [0.20] * 6 + [0.05] * 7 + [0.35] * 9
    )
    plan = optimize(_target_input(7, 90.0, prices=prices))
    assert "soc_target_not_reached" not in plan.warnings
    assert plan.slots[7].soc_end_pct >= 89.5
    mid_charges = [
        s for s in plan.slots[:7]
        if s.action == model.ACTION_CHARGE_GRID and s.start.hour >= 2
    ]
    assert mid_charges
    assert all(s.reason == "soc_target_forced_charge"
               for s in mid_charges)


def test_soc_target_above_soc_max_clamps_and_warns():
    plan = optimize(_target_input(8, 99.0))
    # 99% > soc_max 95% -> clamped, still reachable at 95.
    assert "soc_target_above_soc_max" in plan.warnings
    assert plan.slots[8].soc_end_pct >= 94.5
