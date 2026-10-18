"""DataUpdateCoordinator for Deye Smart Energy Manager."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_ENABLE_CONTROL,
    CONF_ENERGY_EXPORT_ENTITY,
    CONF_ENERGY_IMPORT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_MODE,
    CONF_PRICE_IMPORT_ENTITY,
    CONF_PV_FORECAST_ENTITY,
    CONF_PV_FORECAST_TOMORROW_ENTITY,
    CONF_PV_POWER_ENTITY,
    DEFAULT_MODE,
    DOMAIN,
    MAX_SNAPSHOT_AGE_S,
    UPDATE_INTERVAL_S,
)
from .model import EnergySnapshot

_LOGGER = logging.getLogger(__name__)

_REQUIRED = (
    CONF_PV_POWER_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_POWER_ENTITY,
    CONF_PRICE_IMPORT_ENTITY,
)

_UNAVAIL = ("unavailable", "unknown", "none", "")


class DsemCoordinator(DataUpdateCoordinator[EnergySnapshot]):
    """Read-only coordinator producing a normalized energy snapshot.

    SHADOW-by-design: this coordinator never calls services nor writes
    entities. The optimizer/planner hooks are added in later phases.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_S),
        )
        self._entry = entry

    # -- public properties -------------------------------------------------

    @property
    def mode(self) -> str:
        """Current operating mode from options."""
        return self._entry.options.get(CONF_MODE, DEFAULT_MODE)

    @property
    def control_enabled(self) -> bool:
        """True only when the user explicitly enabled real control."""
        return bool(self._entry.options.get(CONF_ENABLE_CONTROL, False))

    # -- helpers ------------------------------------------------------------

    def _power_w(self, entity_id: str | None, missing: list[str]) -> float | None:
        """Read a power sensor and normalize to W."""
        value = self._float(entity_id, missing)
        if value is None or entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        unit = (
            state.attributes.get("unit_of_measurement", "W")
            if state is not None
            else "W"
        )
        return value * 1000.0 if unit == "kW" else value

    def _float(self, entity_id: str | None, missing: list[str]) -> float | None:
        """Read a numeric state; register missing entities."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state.lower() in _UNAVAIL:
            missing.append(entity_id)
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            missing.append(entity_id)
            return None

    def _stale(self, entity_id: str | None, stale: list[str]) -> None:
        """Flag entities whose data is too old (zero vs unavailable)."""
        if not entity_id:
            return
        state = self.hass.states.get(entity_id)
        if state is not None and (
            dt_util.utcnow() - state.last_updated
        ).total_seconds() > MAX_SNAPSHOT_AGE_S:
            stale.append(entity_id)

    # -- update -------------------------------------------------------------

    async def _async_update_data(self) -> EnergySnapshot:
        """Build a fresh normalized snapshot. Never blocks, never writes."""
        data = self._entry.data
        missing: list[str] = []
        stale: list[str] = []

        for key in _REQUIRED:
            self._stale(data.get(key), stale)

        snapshot = EnergySnapshot(
            timestamp=dt_util.utcnow(),
            pv_power_w=self._power_w(data.get(CONF_PV_POWER_ENTITY), missing),
            grid_power_w=self._power_w(data.get(CONF_GRID_POWER_ENTITY), missing),
            load_power_w=self._power_w(data.get(CONF_LOAD_POWER_ENTITY), missing),
            battery_power_w=self._power_w(
                data.get(CONF_BATTERY_POWER_ENTITY), missing
            ),
            battery_soc_pct=self._float(
                data.get(CONF_BATTERY_SOC_ENTITY), missing
            ),
            price_import_eur_kwh=self._float(
                data.get(CONF_PRICE_IMPORT_ENTITY), missing
            ),
            pv_forecast_today_kwh=self._float(
                data.get(CONF_PV_FORECAST_ENTITY), missing
            ),
            pv_forecast_tomorrow_kwh=self._float(
                data.get(CONF_PV_FORECAST_TOMORROW_ENTITY), missing
            ),
            energy_import_today_kwh=self._float(
                data.get(CONF_ENERGY_IMPORT_ENTITY), missing
            ),
            energy_export_today_kwh=self._float(
                data.get(CONF_ENERGY_EXPORT_ENTITY), missing
            ),
            missing_entities=tuple(missing),
            stale_entities=tuple(stale),
        )
        if missing:
            _LOGGER.debug("DSEM snapshot incomplete, missing: %s", missing)
        return snapshot
