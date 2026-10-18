"""Diagnostics for Deye Smart Energy Manager."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import DsemConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DsemConfigEntry
) -> dict[str, Any]:
    """Return diagnostics: entity mapping, options and latest snapshot.

    Contains no credentials — only entity_ids and numeric parameters.
    """
    coordinator = entry.runtime_data
    snapshot = coordinator.data
    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "mode": coordinator.mode,
        "control_enabled": coordinator.control_enabled,
        "snapshot": asdict(snapshot) if snapshot else None,
    }
