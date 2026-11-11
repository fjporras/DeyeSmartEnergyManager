"""SOC-target number entity for Deye Smart Energy Manager."""
from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DsemConfigEntry
from .const import (
    DEFAULT_TARGET_SOC_PCT,
    DOMAIN,
    MANUFACTURER,
    NAME,
    VERSION,
)
from .targets import KEY_SOC, target_store


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DsemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SOC-target number entity."""
    async_add_entities(
        [DsemTargetSocNumber(hass, entry)], update_before_add=True
    )


class DsemTargetSocNumber(RestoreEntity, NumberEntity):
    """Target battery SOC (%) for the ``target_soc`` mode.

    Value lives in the shared runtime store; the entity restores its
    last state on restart. ``0`` effectively disables the constraint.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "target_soc"
    _attr_icon = "mdi:battery-clock"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.BOX

    def __init__(self, hass: HomeAssistant, entry: DsemConfigEntry) -> None:
        """Initialize the entity."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_target_soc"
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
    def native_value(self) -> float:
        """Current target SOC."""
        return float(self._store.get(KEY_SOC, DEFAULT_TARGET_SOC_PCT))

    async def async_added_to_hass(self) -> None:
        """Restore the last value, if any."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            try:
                self._store[KEY_SOC] = float(state.state)
            except (TypeError, ValueError):
                pass
        self.async_write_ha_state()

    async def async_set_value(self, value: float) -> None:
        """Persist the new target SOC."""
        self._store[KEY_SOC] = max(
            self._attr_native_min_value, min(self._attr_native_max_value, value)
        )
        self.async_write_ha_state()
