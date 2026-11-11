"""Target-time entity for Deye Smart Energy Manager."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DsemConfigEntry
from .const import (
    DEFAULT_TARGET_TIME,
    DOMAIN,
    MANUFACTURER,
    NAME,
    VERSION,
)
from .targets import KEY_TIME, target_store


def _parse_hhmm(value: str) -> dt_time | None:
    """Parse "HH:MM[:SS]" into a time, or None when invalid."""
    try:
        parts = [int(p) for p in value.split(":")]
        if len(parts) < 2:
            return None
        return dt_time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
    except (ValueError, AttributeError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DsemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the target-time entity."""
    async_add_entities(
        [DsemTargetTime(hass, entry)], update_before_add=True
    )


class DsemTargetTime(RestoreEntity, TimeEntity):
    """Wall-clock time by which the target SOC must be reached.

    Time-of-day semantics: the constraint applies to the next
    occurrence of this time within the plan horizon.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "target_time"
    _attr_icon = "mdi:clock-outline"
    _attr_has_date = False

    def __init__(self, hass: HomeAssistant, entry: DsemConfigEntry) -> None:
        """Initialize the entity."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_target_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=NAME,
            sw_version=VERSION,
        )

    @property
    def _store(self) -> dict:
        return target_store(self.hass, self._entry.entry_id)

    @property
    def native_value(self) -> dt_time | None:
        """Current target time."""
        return _parse_hhmm(str(self._store.get(KEY_TIME, DEFAULT_TARGET_TIME)))

    async def async_added_to_hass(self) -> None:
        """Restore the last value, if any."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            parsed = _parse_hhmm(state.state)
            if parsed is not None:
                self._store[KEY_TIME] = parsed.strftime("%H:%M")
        self.async_write_ha_state()

    async def async_set_value(self, value: dt_time) -> None:
        """Persist the new target time."""
        self._store[KEY_TIME] = value.strftime("%H:%M")
        self.async_write_ha_state()
