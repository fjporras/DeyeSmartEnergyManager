"""Operating-mode select for Deye Smart Energy Manager."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DsemConfigEntry
from .const import (
    CONF_MODE,
    CONTROL_MODES,
    DEFAULT_MODE,
    DOMAIN,
    MANUFACTURER,
    MODES,
    NAME,
    VERSION,
)
from .coordinator import DsemCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DsemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DSEM mode select."""
    async_add_entities([DsemModeSelect(entry.runtime_data, entry)])


class DsemModeSelect(CoordinatorEntity[DsemCoordinator], SelectEntity):
    """Select the DSEM operating mode.

    Mode is persisted in the config entry options (single source of
    truth). Control-capable modes are rejected unless the user has
    explicitly enabled real control in the options flow.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "mode"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self, coordinator: DsemCoordinator, entry: DsemConfigEntry
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_options = list(MODES)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=NAME,
            sw_version=VERSION,
        )

    @property
    def current_option(self) -> str:
        """Return the persisted mode."""
        return self._entry.options.get(CONF_MODE, DEFAULT_MODE)

    async def async_select_option(self, option: str) -> None:
        """Persist the new mode, guarding control-capable modes."""
        if option in CONTROL_MODES and not self.coordinator.control_enabled:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="control_not_enabled",
            )
        options = dict(self._entry.options)
        options[CONF_MODE] = option
        self.hass.config_entries.async_update_entry(
            self._entry, options=options
        )
        self.async_write_ha_state()
