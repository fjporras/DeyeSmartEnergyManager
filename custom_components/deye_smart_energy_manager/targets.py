"""Runtime store for the SOC-target mode controls.

The ``number``/``time`` entities write here; the coordinator reads the
same dict every cycle. Values live in ``hass.data`` (runtime only) and
each entity restores its own last state for reboot persistence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .const import (
    DEFAULT_TARGET_SOC_PCT,
    DEFAULT_TARGET_TIME,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

KEY_SOC = "target_soc_pct"
KEY_TIME = "target_time"  # "HH:MM" local wall-clock


def target_store(hass: "HomeAssistant", entry_id: str) -> dict:
    """Per-entry dict holding the SOC-target settings."""
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry_id, {})
    store.setdefault(KEY_SOC, DEFAULT_TARGET_SOC_PCT)
    store.setdefault(KEY_TIME, DEFAULT_TARGET_TIME)
    return store


def target_slot_index(
    first_hour: datetime, horizon: int, target_hhmm: str, now: datetime
) -> int | None:
    """Index of the hourly slot that must end at/above the target SOC.

    ``target_hhmm`` is a wall-clock "HH:MM". The target applies to the
    next occurrence of that time (today if still ahead, else tomorrow).
    The slot is the one *containing* the target time; its ``soc_end``
    must reach the goal. Returns ``None`` when outside the horizon.
    """
    try:
        hh, mm = (int(p) for p in target_hhmm.split(":")[:2])
    except (ValueError, AttributeError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    target_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target_dt <= now:
        target_dt += timedelta(days=1)
    # Slot containing the target time (floor to the hour).
    slot_start = target_dt.replace(minute=0, second=0, microsecond=0)
    idx = int((slot_start - first_hour).total_seconds() // 3600)
    return idx if 0 <= idx < horizon else None
