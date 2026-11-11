"""Bounded executor: plan action -> inverter switch (control modes only).

Scope of v1 control is deliberately narrow: the ONLY writable surface is
the Deye ``battery_grid_charging`` switch — it grants/denies permission
to charge the battery from the grid; the inverter's own logic still
decides power and timing. Nothing else is ever written.

Safety gates (all must pass before any service call):
  * mode in CONTROL_MODES and ``enable_control`` option on
  * plan available with a current slot
  * snapshot complete (no missing/stale required entities)
  * 5-minute grace period after integration start
  * >= CONTROL_MIN_INTERVAL_S between writes (anti-flapping)
  * write is verified by reading the state back; 3 consecutive failures
    open a 30-minute backoff and raise a persistent notification
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
    CONTROL_MODES,
    DEFAULT_GRID_CHARGE_SWITCH_ENTITY,
    DOMAIN,
)
from .model import ACTION_CHARGE_GRID, EnergySnapshot

_LOGGER = logging.getLogger(__name__)

CONTROL_MIN_INTERVAL_S = 600       # anti-flapping between writes
CONTROL_VERIFY_TIMEOUT_S = 8.0     # read-back verification window
CONTROL_BACKOFF_S = 1800           # pause control after repeated failures
CONTROL_STARTUP_GRACE_S = 300      # no writes right after boot
_UNAVAIL = ("unavailable", "unknown", "none", "")


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
