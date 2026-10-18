"""Config flow for Deye Smart Energy Manager (DSEM)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_USABLE_KWH,
    CONF_CHARGE_EFFICIENCY,
    CONF_DEGRADATION_EUR_KWH,
    CONF_DISCHARGE_EFFICIENCY,
    CONF_ENABLE_CONTROL,
    CONF_ENERGY_EXPORT_ENTITY,
    CONF_ENERGY_IMPORT_ENTITY,
    CONF_EXPORT_PRICE_EUR_KWH,
    CONF_GRID_POWER_ENTITY,
    CONF_HORIZON_HOURS,
    CONF_LOAD_POWER_ENTITY,
    CONF_MAX_CHARGE_W,
    CONF_MAX_DISCHARGE_W,
    CONF_MODE,
    CONF_OPTIMIZE_INTERVAL_MIN,
    CONF_PRICE_IMPORT_ENTITY,
    CONF_PV_FORECAST_ENTITY,
    CONF_PV_FORECAST_TOMORROW_ENTITY,
    CONF_PV_PEAK_TODAY_ENTITY,
    CONF_PV_PEAK_TOMORROW_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_RESERVE_SOC_PCT,
    CONF_SOC_MAX_PCT,
    CONF_SOC_MIN_PCT,
    CONF_STEP_MINUTES,
    DEFAULT_BATTERY_POWER_ENTITY,
    DEFAULT_BATTERY_SOC_ENTITY,
    DEFAULT_BATTERY_USABLE_KWH,
    DEFAULT_CHARGE_EFFICIENCY,
    DEFAULT_DEGRADATION_EUR_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY,
    DEFAULT_ENERGY_EXPORT_ENTITY,
    DEFAULT_ENERGY_IMPORT_ENTITY,
    DEFAULT_EXPORT_PRICE_EUR_KWH,
    DEFAULT_GRID_POWER_ENTITY,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_LOAD_POWER_ENTITY,
    DEFAULT_MAX_CHARGE_W,
    DEFAULT_MAX_DISCHARGE_W,
    DEFAULT_MODE,
    DEFAULT_OPTIMIZE_INTERVAL_MIN,
    DEFAULT_PRICE_IMPORT_ENTITY,
    DEFAULT_PV_FORECAST_ENTITY,
    DEFAULT_PV_FORECAST_TOMORROW_ENTITY,
    DEFAULT_PV_PEAK_TODAY_ENTITY,
    DEFAULT_PV_PEAK_TOMORROW_ENTITY,
    DEFAULT_PV_POWER_ENTITY,
    DEFAULT_RESERVE_SOC_PCT,
    DEFAULT_SOC_MAX_PCT,
    DEFAULT_SOC_MIN_PCT,
    DEFAULT_STEP_MINUTES,
    DOMAIN,
    MODES,
    NAME,
)

_POWER_UNITS = {"W", "kW", UnitOfPower.WATT, UnitOfPower.KILO_WATT}
_ENERGY_UNITS = {"Wh", "kWh", "MWh"}
_PCT_UNITS = {"%"}
_PRICE_UNITS = {"€/kWh", "EUR/kWh", "EUR", "€"}


def _validate_entity(
    hass: HomeAssistant,
    entity_id: str,
    expected_units: set[str],
) -> str | None:
    """Return an error key when the entity is missing/unavailable/wrong unit."""
    state = hass.states.get(entity_id)
    if state is None:
        return "entity_missing"
    if state.state in ("unavailable", "unknown"):
        return "entity_unavailable"
    unit = state.attributes.get("unit_of_measurement")
    if unit is not None and unit not in expected_units:
        return "invalid_unit"
    return None


class DsemConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the DSEM config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: required measurement entities."""
        errors: dict[str, str] = {}
        if user_input is not None:
            checks = {
                CONF_PV_POWER_ENTITY: _POWER_UNITS,
                CONF_GRID_POWER_ENTITY: _POWER_UNITS,
                CONF_LOAD_POWER_ENTITY: _POWER_UNITS,
                CONF_BATTERY_SOC_ENTITY: _PCT_UNITS,
                CONF_BATTERY_POWER_ENTITY: _POWER_UNITS,
                CONF_PRICE_IMPORT_ENTITY: _PRICE_UNITS,
            }
            for key, units in checks.items():
                if error := _validate_entity(self.hass, user_input[key], units):
                    errors[key] = error
            if not errors:
                self._required = user_input
                return await self.async_step_optional()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_PV_POWER_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor", device_class="power"
                            )
                        ),
                        vol.Required(CONF_GRID_POWER_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor", device_class="power"
                            )
                        ),
                        vol.Required(CONF_LOAD_POWER_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor", device_class="power"
                            )
                        ),
                        vol.Required(CONF_BATTERY_SOC_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor", device_class="battery"
                            )
                        ),
                        vol.Required(CONF_BATTERY_POWER_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor", device_class="power"
                            )
                        ),
                        vol.Required(CONF_PRICE_IMPORT_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                    }
                ),
                {
                    CONF_PV_POWER_ENTITY: DEFAULT_PV_POWER_ENTITY,
                    CONF_GRID_POWER_ENTITY: DEFAULT_GRID_POWER_ENTITY,
                    CONF_LOAD_POWER_ENTITY: DEFAULT_LOAD_POWER_ENTITY,
                    CONF_BATTERY_SOC_ENTITY: DEFAULT_BATTERY_SOC_ENTITY,
                    CONF_BATTERY_POWER_ENTITY: DEFAULT_BATTERY_POWER_ENTITY,
                    CONF_PRICE_IMPORT_ENTITY: DEFAULT_PRICE_IMPORT_ENTITY,
                },
            ),
            errors=errors,
        )

    async def async_step_optional(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: optional entities (feature degrades gracefully if absent)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            checks = {
                CONF_PV_FORECAST_ENTITY: _ENERGY_UNITS,
                CONF_PV_FORECAST_TOMORROW_ENTITY: _ENERGY_UNITS,
                CONF_PV_PEAK_TODAY_ENTITY: set(),
                CONF_PV_PEAK_TOMORROW_ENTITY: set(),
                CONF_ENERGY_IMPORT_ENTITY: _ENERGY_UNITS,
                CONF_ENERGY_EXPORT_ENTITY: _ENERGY_UNITS,
            }
            data: dict[str, Any] = dict(self._required)
            for key, units in checks.items():
                entity_id = user_input.get(key)
                if entity_id is None:
                    continue
                if error := _validate_entity(self.hass, entity_id, units):
                    errors[key] = error
                else:
                    data[key] = entity_id
            if not errors:
                return self.async_create_entry(title=NAME, data=data)
        return self.async_show_form(
            step_id="optional",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_PV_FORECAST_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                        vol.Optional(
                            CONF_PV_FORECAST_TOMORROW_ENTITY
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                        vol.Optional(
                            CONF_PV_PEAK_TODAY_ENTITY
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                        vol.Optional(
                            CONF_PV_PEAK_TOMORROW_ENTITY
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                        vol.Optional(CONF_ENERGY_IMPORT_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                        vol.Optional(CONF_ENERGY_EXPORT_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="sensor")
                        ),
                    }
                ),
                {
                    CONF_PV_FORECAST_ENTITY: DEFAULT_PV_FORECAST_ENTITY,
                    CONF_PV_FORECAST_TOMORROW_ENTITY: DEFAULT_PV_FORECAST_TOMORROW_ENTITY,
                    CONF_PV_PEAK_TODAY_ENTITY: DEFAULT_PV_PEAK_TODAY_ENTITY,
                    CONF_PV_PEAK_TOMORROW_ENTITY: DEFAULT_PV_PEAK_TOMORROW_ENTITY,
                    CONF_ENERGY_IMPORT_ENTITY: DEFAULT_ENERGY_IMPORT_ENTITY,
                    CONF_ENERGY_EXPORT_ENTITY: DEFAULT_ENERGY_EXPORT_ENTITY,
                },
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DsemOptionsFlow:
        """Return the options flow."""
        return DsemOptionsFlow()


class DsemOptionsFlow(config_entries.OptionsFlow):
    """Battery, optimizer, price and control options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit DSEM options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_SOC_MIN_PCT] >= user_input[CONF_SOC_MAX_PCT]:
                errors["base"] = "soc_range"
            if user_input[CONF_RESERVE_SOC_PCT] <= user_input[CONF_SOC_MIN_PCT]:
                errors[CONF_RESERVE_SOC_PCT] = "reserve_below_min"
            if not errors:
                return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_MODE): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=list(MODES),
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key="mode",
                            )
                        ),
                        vol.Required(CONF_ENABLE_CONTROL): selector.BooleanSelector(),
                        vol.Required(CONF_BATTERY_USABLE_KWH): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1,
                                max=200,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="kWh",
                            )
                        ),
                        vol.Required(CONF_SOC_MIN_PCT): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=100,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="%",
                            )
                        ),
                        vol.Required(CONF_SOC_MAX_PCT): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=100,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="%",
                            )
                        ),
                        vol.Required(CONF_RESERVE_SOC_PCT): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=100,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="%",
                            )
                        ),
                        vol.Required(CONF_MAX_CHARGE_W): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=24000,
                                step=50,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="W",
                            )
                        ),
                        vol.Required(CONF_MAX_DISCHARGE_W): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=24000,
                                step=50,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="W",
                            )
                        ),
                        vol.Required(CONF_CHARGE_EFFICIENCY): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.5,
                                max=1,
                                step=0.01,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(CONF_DISCHARGE_EFFICIENCY): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.5,
                                max=1,
                                step=0.01,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(CONF_DEGRADATION_EUR_KWH): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=1,
                                step=0.005,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="€/kWh",
                            )
                        ),
                        vol.Required(CONF_HORIZON_HOURS): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=6,
                                max=72,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="h",
                            )
                        ),
                        vol.Required(CONF_STEP_MINUTES): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=15,
                                max=120,
                                step=15,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                        vol.Required(CONF_OPTIMIZE_INTERVAL_MIN): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=5,
                                max=120,
                                step=5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                        vol.Required(CONF_EXPORT_PRICE_EUR_KWH): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=1,
                                step=0.005,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="€/kWh",
                            )
                        ),
                    }
                ),
                {
                    CONF_MODE: options.get(CONF_MODE, DEFAULT_MODE),
                    CONF_ENABLE_CONTROL: options.get(CONF_ENABLE_CONTROL, False),
                    CONF_BATTERY_USABLE_KWH: options.get(
                        CONF_BATTERY_USABLE_KWH, DEFAULT_BATTERY_USABLE_KWH
                    ),
                    CONF_SOC_MIN_PCT: options.get(CONF_SOC_MIN_PCT, DEFAULT_SOC_MIN_PCT),
                    CONF_SOC_MAX_PCT: options.get(CONF_SOC_MAX_PCT, DEFAULT_SOC_MAX_PCT),
                    CONF_RESERVE_SOC_PCT: options.get(
                        CONF_RESERVE_SOC_PCT, DEFAULT_RESERVE_SOC_PCT
                    ),
                    CONF_MAX_CHARGE_W: options.get(
                        CONF_MAX_CHARGE_W, DEFAULT_MAX_CHARGE_W
                    ),
                    CONF_MAX_DISCHARGE_W: options.get(
                        CONF_MAX_DISCHARGE_W, DEFAULT_MAX_DISCHARGE_W
                    ),
                    CONF_CHARGE_EFFICIENCY: options.get(
                        CONF_CHARGE_EFFICIENCY, DEFAULT_CHARGE_EFFICIENCY
                    ),
                    CONF_DISCHARGE_EFFICIENCY: options.get(
                        CONF_DISCHARGE_EFFICIENCY, DEFAULT_DISCHARGE_EFFICIENCY
                    ),
                    CONF_DEGRADATION_EUR_KWH: options.get(
                        CONF_DEGRADATION_EUR_KWH, DEFAULT_DEGRADATION_EUR_KWH
                    ),
                    CONF_HORIZON_HOURS: options.get(
                        CONF_HORIZON_HOURS, DEFAULT_HORIZON_HOURS
                    ),
                    CONF_STEP_MINUTES: options.get(
                        CONF_STEP_MINUTES, DEFAULT_STEP_MINUTES
                    ),
                    CONF_OPTIMIZE_INTERVAL_MIN: options.get(
                        CONF_OPTIMIZE_INTERVAL_MIN, DEFAULT_OPTIMIZE_INTERVAL_MIN
                    ),
                    CONF_EXPORT_PRICE_EUR_KWH: options.get(
                        CONF_EXPORT_PRICE_EUR_KWH, DEFAULT_EXPORT_PRICE_EUR_KWH
                    ),
                },
            ),
            errors=errors,
        )
