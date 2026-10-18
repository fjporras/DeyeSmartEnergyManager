"""Deye Smart Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .coordinator import DsemCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SELECT]

DsemConfigEntry = ConfigEntry[DsemCoordinator]

SERVICE_REOPTIMIZE = "reoptimize"


async def async_setup_entry(hass: HomeAssistant, entry: DsemConfigEntry) -> bool:
    """Set up DSEM from a config entry."""
    coordinator = DsemCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DsemConfigEntry) -> bool:
    """Unload DSEM: platforms only, coordinator holds no resources."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: DsemConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register DSEM services once (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_REOPTIMIZE):
        return

    async def _handle_reoptimize(call: ServiceCall) -> None:
        """Force an immediate snapshot/optimization refresh."""
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REOPTIMIZE, _handle_reoptimize)
