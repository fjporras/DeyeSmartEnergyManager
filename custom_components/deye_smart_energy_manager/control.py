"""Bounded executor: plan action -> inverter entities (control modes).

Writable surface (all gated by mode + ``enable_control``):
  * ``battery_grid_charging`` switch — grants/denies grid-charge
    permission; the inverter's own logic decides power and timing.
  * Zero-export guard — keeps ``work_mode`` at ``Zero Export To CT``,
    ``export_surplus`` off and ``zero_export_power`` at 20 W, so the
    export configuration — ``auto_export`` enforces ``Export First`` +
    ``export_surplus`` on + ``energy_pattern`` ``Battery First``
    (surplus PV may be sold to the grid, but the battery takes it
    first); every other executor mode enforces zero-export
    (``Zero Export To CT`` + ``export_surplus`` off + 20 W margin).
  * ``off_grid`` guard — ON only while the plan expects the battery to
    serve the load (``discharge`` slots), OFF otherwise because it
    blocks grid charging. Verified live: this inverter only discharges
    to the house load when ``off_grid`` is ON.

Safety gates (all must pass before any service call):
  * mode in CONTROL_MODES and ``enable_control`` option on
  * plan available with a current slot (switch writes only)
  * snapshot complete (no missing/stale required entities, switch only)
  * 5-minute grace period after integration start
  * >= CONTROL_MIN_INTERVAL_S between writes (anti-flapping)
  * write is verified by reading the state back; 3 consecutive failures
    open a 30-minute backoff and raise a persistent notification
  * inverter protections (``*_protection_*``, SOC shutdown/low,
    voltages, TOU programs) are NEVER written
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENABLE_CONTROL,
    CONF_GRID_CHARGE_SWITCH_ENTITY,
    CONF_PVPC_AUTOMATION_ENTITY,
    CONTROL_MODES,
    DEFAULT_GRID_CHARGE_SWITCH_ENTITY,
    DEFAULT_PVPC_AUTOMATION_ENTITY,
    MODE_AUTO_EXPORT,
    DOMAIN,
)
from .model import (
    ACTION_CHARGE_GRID,
    ACTION_DISCHARGE,
    EnergySnapshot,
)

_LOGGER = logging.getLogger(__name__)

CONTROL_MIN_INTERVAL_S = 600       # anti-flapping between writes
CONTROL_VERIFY_TIMEOUT_S = 8.0     # read-back verification window
CONTROL_BACKOFF_S = 1800           # pause control after repeated failures
CONTROL_STARTUP_GRACE_S = 300      # no writes right after boot
_UNAVAIL = ("unavailable", "unknown", "none", "")

# Export-mode guard targets: ``auto_export`` allows surplus PV to be
# sold to the grid (verified live 2026-11-20 after the service-entrance
# rewiring removed the voltage regulator that distorted the CT reading
# and made zero-export regulate a false setpoint).
EXPORT_WORK_MODE = "Export First"

# Energy-pattern guard target (verified live 2026-11-22): with
# ``energy_pattern`` at ``Load First`` this inverter skips the battery
# for GEN-port PV surplus entirely — PV serves load then exports while
# the battery stays idle even in ``charge_pv`` slots. ``Battery First``
# routes the surplus into the battery first (observed: battery −4.7 kW
# charging, grid exchange ~0 W), so it is enforced in ``auto_export``.
EXPORT_ENERGY_PATTERN = "Battery First"

# Zero-export guard targets (verified live 2026-11-15): the inverter
# must not export — there is no physical export path, so surplus PV
# beyond battery capacity is curtailed by the inverter itself.
ZERO_EXPORT_WORK_MODE = "Zero Export To CT"
ZERO_EXPORT_MARGIN_W = 20.0

# Off-grid guard (verified live 2026-11-16): on this inverter ``off_grid``
# is the ONLY switch that lets the battery discharge to serve the house
# load — with it OFF the battery stays idle and the grid pays everything.
# The same switch also BLOCKS grid charging, so it must be OFF whenever
# the plan calls for ``charge_grid``. Mapping: ON only for discharge
# slots, OFF for everything else.
OFFGRID_MIN_SOC_PCT = 12.0  # never force discharge below physical floor


async def async_apply_control(
    hass: HomeAssistant,
    entry,
    coordinator,
    snapshot: EnergySnapshot,
) -> str | None:
    """Apply the current plan slot to the grid-charging switch.

    Returns a short status string for ``plan_meta['control']``, or
    ``None`` when control is not active. Never raises.
    """
    try:
        return await _apply(hass, entry, coordinator, snapshot)
    except Exception as err:  # noqa: BLE001 - control must never break updates
        _LOGGER.warning("DSEM control error: %s", err)
        return "control_error"


async def _apply(hass, entry, coordinator, snapshot) -> str | None:
    if coordinator.mode not in CONTROL_MODES:
        return None
    if not entry.options.get(CONF_ENABLE_CONTROL, False):
        return "control_disabled_option"
    now = dt_util.now()
    backoff = getattr(coordinator, "_control_backoff_until", None)
    if backoff and now < backoff:
        return "control_backoff"
    ready_at = getattr(coordinator, "_control_ready_at", None)
    if ready_at and now < ready_at:
        return "control_startup_grace"
    plan = coordinator.plan
    if plan is None or plan.current_slot is None:
        return "control_no_plan"
    if snapshot.missing_entities or snapshot.stale_entities:
        return "control_unsafe_data"

    entity_id = entry.options.get(
        CONF_GRID_CHARGE_SWITCH_ENTITY, DEFAULT_GRID_CHARGE_SWITCH_ENTITY
    )
    state = hass.states.get(entity_id)
    if state is None or state.state.lower() in _UNAVAIL:
        return "control_switch_unavailable"

    want_on = plan.current_slot.action == ACTION_CHARGE_GRID
    want = "on" if want_on else "off"
    if state.state == want:
        coordinator._control_failures = 0
        return f"control_ok:{want}"

    last_write = getattr(coordinator, "_control_last_write", None)
    if last_write and (now - last_write).total_seconds() < CONTROL_MIN_INTERVAL_S:
        return "control_rate_limited"

    ok = await _write_and_verify(hass, entity_id, want)
    coordinator._control_last_write = now
    if ok:
        coordinator._control_failures = 0
        _notify_once(hass, entry, entity_id)
        _LOGGER.info(
            "DSEM control: %s -> %s (plan action %s)",
            entity_id, want, plan.current_slot.action,
        )
        return f"control_written:{want}"
    failures = getattr(coordinator, "_control_failures", 0) + 1
    coordinator._control_failures = failures
    if failures >= 3:
        coordinator._control_backoff_until = now + timedelta(
            seconds=CONTROL_BACKOFF_S
        )
        _LOGGER.error(
            "DSEM control: %d consecutive write failures on %s — backoff %ds",
            failures, entity_id, CONTROL_BACKOFF_S,
        )
        hass.async_create_task(
            hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "DSEM — control en backoff",
                    "message": (
                        f"{failures} fallos consecutivos escribiendo "
                        f"{entity_id}. Control pausado {CONTROL_BACKOFF_S // 60} min."
                    ),
                    "notification_id": f"dsem_control_backoff_{entry.entry_id}",
                },
            )
        )
        return "control_write_failed_backoff"
    return "control_write_failed"


def _conflict_marker_key(entry_id: str) -> str:
    return f"{DOMAIN}_conflict_prev_{entry_id}"


async def async_manage_conflicting_automation(
    hass: HomeAssistant, entry, coordinator
) -> str | None:
    """Suspend/restore the legacy PVPC automation that shares the switch.

    While an executor mode with ``enable_control`` is active, the PVPC
    automation (which also writes ``battery_grid_charging``) is turned
    off so both controllers don't fight over the same resource. When
    DSEM leaves executor modes, the automation is restored to the state
    it had before DSEM suspended it. Never raises.
    """
    try:
        return await _manage_conflict(hass, entry, coordinator)
    except Exception as err:  # noqa: BLE001 - must never break updates
        _LOGGER.warning("DSEM conflict-manager error: %s", err)
        return None


async def _manage_conflict(hass, entry, coordinator) -> str | None:
    active = (
        coordinator.mode in CONTROL_MODES
        and entry.options.get(CONF_ENABLE_CONTROL, False)
    )
    entity_id = entry.options.get(
        CONF_PVPC_AUTOMATION_ENTITY, DEFAULT_PVPC_AUTOMATION_ENTITY
    )
    state = hass.states.get(entity_id)
    if state is None:
        return None
    marker = _conflict_marker_key(entry.entry_id)
    store = hass.data.setdefault(DOMAIN, {})
    prev = store.get(marker)

    if active:
        if state.state != "on":
            # Already off (manually or by us); keep any stored prev state.
            return None
        if prev is None:
            store[marker] = "on"
            _LOGGER.info(
                "DSEM: suspending conflicting automation %s "
                "(executor mode %s)", entity_id, coordinator.mode,
            )
        else:
            _LOGGER.debug(
                "DSEM: re-suspending %s (still in executor mode)", entity_id
            )
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": entity_id}
        )
        _notify_conflict(hass, entry, entity_id, suspended=True)
        return "conflict_suspended"

    if prev is not None:
        del store[marker]
        service = "turn_on" if prev == "on" else "turn_off"
        await hass.services.async_call(
            "automation", service, {"entity_id": entity_id}
        )
        _LOGGER.info(
            "DSEM: restored conflicting automation %s to '%s'",
            entity_id, prev,
        )
        _notify_conflict(hass, entry, entity_id, suspended=False)
        return "conflict_restored"
    return None


def _notify_conflict(
    hass: HomeAssistant, entry, entity_id: str, *, suspended: bool
) -> None:
    """One-shot persistent notification about the automation handover."""
    key = f"{DOMAIN}_conflict_notified_{'suspend' if suspended else 'restore'}_{entry.entry_id}_{entity_id}"
    store = hass.data.setdefault(DOMAIN, {})
    if store.get(key):
        return
    store[key] = True
    title = (
        "DSEM — automatización PVPC en pausa"
        if suspended
        else "DSEM — automatización PVPC restaurada"
    )
    message = (
        f"{entity_id} se ha desactivado porque DSEM controla "
        "battery_grid_charging en modo ejecutor. Se restaurará al "
        "volver a shadow/manual/safe."
        if suspended
        else f"{entity_id} vuelve a su estado anterior tras salir "
        "del modo ejecutor de DSEM."
    )
    hass.async_create_task(
        hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"dsem_conflict_{entry.entry_id}",
            },
        )
    )


async def async_apply_zero_export_guard(
    hass: HomeAssistant, entry, coordinator
) -> str | None:
    """Keep the inverter's export configuration aligned with the mode.

    Executor modes other than ``auto_export`` enforce zero-export:
    ``work_mode`` (``Zero Export To CT``), ``export_surplus`` (off) and
    ``zero_export_power`` (20 W margin). ``auto_export`` flips the goal
    to ``Export First`` + ``export_surplus`` on so surplus PV can be
    sold to the grid. Writes whichever deviates, one entity per call,
    under the same safety gates as the grid-charge switch. Returns a
    short status for ``plan_meta['zero_export']``; ``None`` when
    inactive. Never raises.
    """
    try:
        return await _zero_export_guard(hass, entry, coordinator)
    except Exception as err:  # noqa: BLE001 - control must never break updates
        _LOGGER.warning("DSEM zero-export guard error: %s", err)
        return "ze_error"


async def _zero_export_guard(hass, entry, coordinator) -> str | None:
    if coordinator.mode not in CONTROL_MODES:
        return None
    if not entry.options.get(CONF_ENABLE_CONTROL, False):
        return None
    now = dt_util.now()
    ready_at = getattr(coordinator, "_control_ready_at", None)
    if ready_at and now < ready_at:
        return "ze_startup_grace"
    backoff = getattr(coordinator, "_control_backoff_until", None)
    if backoff and now < backoff:
        return "ze_backoff"
    prefix = coordinator._entity_prefix()
    if not prefix:
        return "ze_no_prefix"

    # ``auto_export`` flips the guard's goal: enforce the export-permit
    # configuration instead of the zero-export one. ``zero_export_power``
    # is irrelevant in export mode and left untouched.
    if coordinator.mode == MODE_AUTO_EXPORT:
        targets = (
            (
                f"select.{prefix}_work_mode",
                EXPORT_WORK_MODE,
                "select", "select_option",
                {"option": EXPORT_WORK_MODE},
            ),
            (
                f"switch.{prefix}_export_surplus",
                "on",
                "switch", "turn_on",
                {},
            ),
            (
                f"select.{prefix}_energy_pattern",
                EXPORT_ENERGY_PATTERN,
                "select", "select_option",
                {"option": EXPORT_ENERGY_PATTERN},
            ),
        )
    else:
        targets = (
            (
                f"select.{prefix}_work_mode",
                ZERO_EXPORT_WORK_MODE,
                "select", "select_option",
                {"option": ZERO_EXPORT_WORK_MODE},
            ),
            (
                f"switch.{prefix}_export_surplus",
                "off",
                "switch", "turn_off",
                {},
            ),
            (
                f"number.{prefix}_zero_export_power",
                ZERO_EXPORT_MARGIN_W,
                "number", "set_value",
                {"value": ZERO_EXPORT_MARGIN_W},
            ),
        )
    saw_unavailable = False
    for entity_id, want, domain, service, extra in targets:
        state = hass.states.get(entity_id)
        if state is None or state.state.lower() in _UNAVAIL:
            saw_unavailable = True
            continue
        if _state_matches(state.state, want):
            continue
        # First mismatch wins; one write per cycle (min-dwell shared
        # with the grid-charge switch via _control_last_write).
        last_write = getattr(coordinator, "_control_last_write", None)
        if last_write and (now - last_write).total_seconds() \
                < CONTROL_MIN_INTERVAL_S:
            return "ze_rate_limited"
        ok = await _write_entity_and_verify(
            hass, entity_id, domain, service,
            {"entity_id": entity_id, **extra}, want,
        )
        coordinator._control_last_write = now
        if ok:
            _LOGGER.info(
                "DSEM zero-export: %s -> %s", entity_id, want
            )
            return f"ze_written:{entity_id}"
        return "ze_write_failed"
    if saw_unavailable:
        return "ze_unavailable"
    return "ze_ok"


async def async_apply_offgrid_guard(
    hass: HomeAssistant,
    entry,
    coordinator,
    snapshot: EnergySnapshot,
) -> str | None:
    """Keep ``off_grid`` aligned with the plan's discharge needs.

    ON only while the current slot expects the battery to serve the
    load (``discharge`` action); OFF otherwise because it blocks grid
    charging. Same safety gates as the other writers, plus: never
    writes ON while grid voltage is below 150 V (the outage automation
    owns ``off_grid`` then — note ``binary_sensor.*_grid`` reads off
    whenever exchange is zero, so it is not a presence signal), and
    never forces ON below ``OFFGRID_MIN_SOC_PCT``. On leaving executor
    modes a DSEM-owned ON state is restored to OFF. Never raises.
    """
    try:
        return await _offgrid_guard(hass, entry, coordinator, snapshot)
    except Exception as err:  # noqa: BLE001 - control must never break updates
        _LOGGER.warning("DSEM off-grid guard error: %s", err)
        return "og_error"


async def _offgrid_guard(hass, entry, coordinator, snapshot) -> str | None:
    active = (
        coordinator.mode in CONTROL_MODES
        and entry.options.get(CONF_ENABLE_CONTROL, False)
    )
    prefix = coordinator._entity_prefix()
    entity_id = f"switch.{prefix}_off_grid" if prefix else None
    marker = f"{DOMAIN}_offgrid_owned_{entry.entry_id}"
    store = hass.data.setdefault(DOMAIN, {})

    if not active:
        # Restore a DSEM-owned ON state when control is no longer active.
        if entity_id and store.pop(marker, False):
            state = hass.states.get(entity_id)
            if state is not None and state.state == "on":
                try:
                    await hass.services.async_call(
                        "switch", "turn_off", {"entity_id": entity_id}
                    )
                    _LOGGER.info(
                        "DSEM off-grid: restored %s to off", entity_id
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("DSEM off-grid restore failed: %s", err)
        return None

    now = dt_util.now()
    backoff = getattr(coordinator, "_offgrid_backoff_until", None)
    if backoff and now < backoff:
        return "og_backoff"
    ready_at = getattr(coordinator, "_control_ready_at", None)
    if ready_at and now < ready_at:
        return "og_startup_grace"
    plan = coordinator.plan
    if plan is None or plan.current_slot is None:
        return "og_no_plan"
    if snapshot.missing_entities or snapshot.stale_entities:
        return "og_unsafe_data"
    if not entity_id:
        return "og_no_entity"

    want_on = plan.current_slot.action == ACTION_DISCHARGE
    state = hass.states.get(entity_id)
    if state is None or state.state.lower() in _UNAVAIL:
        return "og_unavailable"

    if want_on:
        # Do not fight the outage automation: if the grid voltage is
        # genuinely absent the island logic owns this switch. NOTE the
        # ``binary_sensor.<prefix>_grid`` flag reads OFF whenever grid
        # exchange is zero (verified live) — it is NOT a grid-presence
        # signal, so voltage is the reliable check.
        voltage = hass.states.get(f"sensor.{prefix}_grid_l1_voltage")
        if voltage is not None and voltage.state not in _UNAVAIL:
            try:
                if float(voltage.state) < 150.0:
                    return "og_grid_down"
            except (TypeError, ValueError):
                pass
        soc = snapshot.battery_soc_pct
        if soc is not None and soc <= OFFGRID_MIN_SOC_PCT:
            return "og_low_soc"

    want = "on" if want_on else "off"
    if state.state == want:
        if want_on:
            store[marker] = True
        else:
            store.pop(marker, None)
        coordinator._offgrid_failures = 0
        return f"og_ok:{want}"

    last_write = getattr(coordinator, "_offgrid_last_write", None)
    if last_write and (now - last_write).total_seconds() \
            < CONTROL_MIN_INTERVAL_S:
        return "og_rate_limited"

    ok = await _write_and_verify(hass, entity_id, want)
    coordinator._offgrid_last_write = now
    if ok:
        coordinator._offgrid_failures = 0
        if want_on:
            store[marker] = True
        else:
            store.pop(marker, None)
        _LOGGER.info(
            "DSEM off-grid: %s -> %s (plan action %s)",
            entity_id, want, plan.current_slot.action,
        )
        return f"og_written:{want}"
    failures = getattr(coordinator, "_offgrid_failures", 0) + 1
    coordinator._offgrid_failures = failures
    if failures >= 3:
        coordinator._offgrid_backoff_until = now + timedelta(
            seconds=CONTROL_BACKOFF_S
        )
        _LOGGER.error(
            "DSEM off-grid: %d consecutive write failures on %s",
            failures, entity_id,
        )
        return "og_write_failed_backoff"
    return "og_write_failed"


def _state_matches(actual: str, want) -> bool:
    """Compare a state string to a string or numeric target."""
    if isinstance(want, str):
        return actual.strip().lower() == want.strip().lower()
    try:
        return abs(float(actual) - float(want)) < 0.51
    except (TypeError, ValueError):
        return False


async def _write_entity_and_verify(
    hass: HomeAssistant,
    entity_id: str,
    domain: str,
    service: str,
    params: dict,
    want,
) -> bool:
    """Generic guarded write + read-back verification."""
    deadline = asyncio.get_running_loop().time() + CONTROL_VERIFY_TIMEOUT_S
    try:
        await hass.services.async_call(
            domain, service, params, blocking=True
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("DSEM %s call failed (%s): %s", domain, service, err)
        return False
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(1.0)
        state = hass.states.get(entity_id)
        if state is not None and _state_matches(state.state, want):
            return True
    return False


async def _write_and_verify(hass: HomeAssistant, entity_id: str, want: str) -> bool:
    """Turn the switch and confirm the state actually changed."""
    service = "turn_on" if want == "on" else "turn_off"
    deadline = asyncio.get_running_loop().time() + CONTROL_VERIFY_TIMEOUT_S
    for attempt in range(2):
        try:
            await hass.services.async_call(
                "switch", service, {"entity_id": entity_id}, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("DSEM control call failed (%s): %s", service, err)
            return False
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1.0)
            state = hass.states.get(entity_id)
            if state is not None and state.state == want:
                return True
        if attempt == 0:
            deadline = asyncio.get_running_loop().time() + 4.0
    return False


def _notify_once(hass: HomeAssistant, entry, entity_id: str) -> None:
    """One-shot persistent notification the first time DSEM writes."""
    marker = f"{DOMAIN}_control_notified_{entry.entry_id}"
    if hass.data.setdefault(DOMAIN, {}).get(marker):
        return
    hass.data[DOMAIN][marker] = True
    hass.async_create_task(
        hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "DSEM — control activo",
                "message": (
                    f"DSEM está controlando {entity_id} según el plan. "
                    "Para devolver el control al inversor, cambia el modo "
                    "a shadow o desactiva enable_control en opciones."
                ),
                "notification_id": f"dsem_control_active_{entry.entry_id}",
            },
        )
    )
