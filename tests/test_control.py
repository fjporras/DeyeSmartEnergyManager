"""Unit tests for the ``off_grid`` guard persistence hysteresis."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from dsem import control
from dsem.const import (
    CONF_ENABLE_CONTROL,
    CONF_RESERVE_SOC_PCT,
    DOMAIN,
)
from dsem.model import EnergySnapshot

P = control.OFFGRID_WRITE_PERSIST_EVALS
PREFIX = "deye_sun"
SWITCH = f"switch.{PREFIX}_off_grid"
VOLTAGE = f"sensor.{PREFIX}_grid_l1_voltage"


class _State:
    def __init__(self, state):
        self.state = state
        self.attributes = {}


class _States:
    def __init__(self, mapping):
        self.map = dict(mapping)

    def get(self, entity_id):
        value = self.map.get(entity_id)
        return None if value is None else _State(value)


class _Services:
    def __init__(self, states):
        self._states = states
        self.calls = []

    async def async_call(self, domain, service, params, blocking=False):
        self.calls.append((domain, service, params))
        if domain == "switch":
            self._states.map[params["entity_id"]] = (
                "on" if service == "turn_on" else "off"
            )


class _Hass:
    def __init__(self, states):
        self.data = {}
        self.states = _States(states)
        self.services = _Services(self.states)


class _Entry:
    def __init__(self, enable=True):
        self.entry_id = "test"
        self.options = {CONF_ENABLE_CONTROL: enable}


class _Coordinator:
    def __init__(self, action, mode="auto"):
        self.mode = mode
        self.plan = SimpleNamespace(
            current_slot=SimpleNamespace(action=action)
        )

    def _entity_prefix(self):
        return PREFIX


def _snap(soc=50.0, ev_state=None):
    return EnergySnapshot(
        timestamp=datetime.now(timezone.utc),
        battery_soc_pct=soc,
        ev_state=ev_state,
    )


def _run(hass, entry, coord, snapshot):
    return asyncio.run(
        control._offgrid_guard(hass, entry, coord, snapshot)
    )


def _env(switch="off", action="discharge", voltage="230", soc=50.0):
    hass = _Hass({SWITCH: switch, VOLTAGE: voltage})
    return hass, _Entry(), _Coordinator(action), _snap(soc)


def test_write_requires_stable_demand():
    hass, entry, coord, snap = _env(switch="off", action="discharge")
    for n in range(1, P):
        status = _run(hass, entry, coord, snap)
        assert status == f"og_pending:on:{n}", status
        assert hass.services.calls == []
    assert _run(hass, entry, coord, snap) == "og_written:on"
    assert hass.states.map[SWITCH] == "on"
    marker = f"{DOMAIN}_offgrid_owned_{entry.entry_id}"
    assert hass.data[DOMAIN][marker] is True


def test_plan_flap_never_writes():
    hass = _Hass({SWITCH: "on", VOLTAGE: "230"})
    entry, coord = _Entry(), _Coordinator("discharge")
    snap = _snap()
    for _ in range(3 * P):
        coord.plan = SimpleNamespace(
            current_slot=SimpleNamespace(action="import")
        )
        assert _run(hass, entry, coord, snap) == "og_pending:off:1"
        coord.plan = SimpleNamespace(
            current_slot=SimpleNamespace(action="discharge")
        )
        assert _run(hass, entry, coord, snap) == "og_ok:on"
    assert hass.services.calls == []


def test_flap_in_off_state_never_writes():
    hass = _Hass({SWITCH: "off", VOLTAGE: "230"})
    entry, coord = _Entry(), _Coordinator("import")
    snap = _snap()
    for _ in range(3 * P):
        coord.plan = SimpleNamespace(
            current_slot=SimpleNamespace(action="discharge")
        )
        assert _run(hass, entry, coord, snap) == "og_pending:on:1"
        coord.plan = SimpleNamespace(
            current_slot=SimpleNamespace(action="import")
        )
        assert _run(hass, entry, coord, snap) == "og_ok:off"
    assert hass.services.calls == []


def test_low_soc_off_bypasses_hysteresis_and_rate_limit():
    hass, entry, coord, snap = _env(
        switch="on", action="import", soc=10.0
    )
    # A recent write would normally rate-limit — the SOC-floor OFF is
    # a protection write and must go through immediately.
    coord._offgrid_last_write = control.dt_util.now()
    assert _run(hass, entry, coord, snap) == "og_written:off"
    assert hass.states.map[SWITCH] == "off"


def test_low_soc_blocks_want_on():
    hass, entry, coord, snap = _env(
        switch="off", action="discharge", soc=10.0
    )
    assert _run(hass, entry, coord, snap) == "og_low_soc"
    assert hass.services.calls == []


def test_grid_down_blocks_want_on():
    hass, entry, coord, snap = _env(
        switch="off", action="discharge", voltage="100"
    )
    assert _run(hass, entry, coord, snap) == "og_grid_down"
    assert hass.services.calls == []


def test_persisted_demand_still_rate_limited():
    hass, entry, coord, snap = _env(switch="off", action="discharge")
    coord._offgrid_last_write = control.dt_util.now()
    for _ in range(P):
        _run(hass, entry, coord, snap)
    assert _run(hass, entry, coord, snap) == "og_rate_limited"
    assert hass.services.calls == []


def test_leaving_executor_restores_owned_on():
    hass = _Hass({SWITCH: "on"})
    entry = _Entry()
    coord = _Coordinator("discharge", mode="shadow")
    hass.data[DOMAIN] = {
        f"{DOMAIN}_offgrid_owned_{entry.entry_id}": True
    }
    assert _run(hass, entry, coord, _snap()) is None
    assert hass.states.map[SWITCH] == "off"


def test_state_match_resets_pending():
    hass, entry, coord, snap = _env(switch="off", action="discharge")
    for _ in range(3):
        _run(hass, entry, coord, snap)
    hass.states.map[SWITCH] = "on"  # external write mid-persistence
    assert _run(hass, entry, coord, snap) == "og_ok:on"
    assert coord._offgrid_pending_count == 0


def test_ev_floor_latch_holds_off_until_session_ends():
    # Islanded + EV charging, SOC reaches the reserve floor: the OFF
    # bypasses persistence like the low-SOC protection write.
    hass, entry, coord, snap = _env(
        switch="on", action="discharge", soc=40.0
    )
    entry.options[CONF_RESERVE_SOC_PCT] = 40.0
    snap = _snap(soc=40.0, ev_state="charging")
    assert _run(hass, entry, coord, snap) == "og_written:off"
    assert hass.states.map[SWITCH] == "off"
    # While the session continues the latch holds OFF even with a
    # recovered SOC and a plan still wanting discharge.
    snap = _snap(soc=60.0, ev_state="charging")
    for _ in range(2 * P):
        assert _run(hass, entry, coord, snap) == "og_ev_floor_hold"
    assert hass.states.map[SWITCH] == "off"
    # Charge ends: the latch releases and the plan may island again.
    coord._offgrid_last_write = None
    snap = _snap(soc=60.0, ev_state="sleep")
    for _ in range(P - 1):
        assert _run(hass, entry, coord, snap).startswith("og_pending:on")
    assert _run(hass, entry, coord, snap) == "og_written:on"
    assert hass.states.map[SWITCH] == "on"


def test_ev_latch_blocks_island_when_already_below_floor():
    hass, entry, coord, snap = _env(
        switch="off", action="discharge", soc=30.0
    )
    entry.options[CONF_RESERVE_SOC_PCT] = 40.0
    snap = _snap(soc=30.0, ev_state="charging")
    for _ in range(2 * P):
        assert _run(hass, entry, coord, snap) == "og_ev_floor_hold"
    assert hass.services.calls == []
