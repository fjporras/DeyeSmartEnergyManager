"""Constants for Deye Smart Energy Manager (DSEM)."""
from __future__ import annotations

DOMAIN = "deye_smart_energy_manager"
NAME = "Deye Smart Energy Manager"
MANUFACTURER = "DSEM"
VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Config entry data keys (entity_id mappings chosen in the config flow)
# ---------------------------------------------------------------------------
CONF_PV_POWER_ENTITY = "pv_power_entity"
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_LOAD_POWER_ENTITY = "load_power_entity"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_BATTERY_POWER_ENTITY = "battery_power_entity"
CONF_PRICE_IMPORT_ENTITY = "price_import_entity"
CONF_PV_FORECAST_ENTITY = "pv_forecast_entity"
CONF_PV_FORECAST_TOMORROW_ENTITY = "pv_forecast_tomorrow_entity"
CONF_PV_PEAK_TODAY_ENTITY = "pv_peak_today_entity"
CONF_PV_PEAK_TOMORROW_ENTITY = "pv_peak_tomorrow_entity"
CONF_ENERGY_IMPORT_ENTITY = "energy_import_entity"
CONF_ENERGY_EXPORT_ENTITY = "energy_export_entity"

# ---------------------------------------------------------------------------
# Options keys (physical/optimizer parameters)
# ---------------------------------------------------------------------------
CONF_BATTERY_USABLE_KWH = "battery_usable_kwh"
CONF_SOC_MIN_PCT = "soc_min_pct"
CONF_SOC_MAX_PCT = "soc_max_pct"
CONF_RESERVE_SOC_PCT = "reserve_soc_pct"
CONF_MAX_CHARGE_W = "max_charge_w"
CONF_MAX_DISCHARGE_W = "max_discharge_w"
CONF_CHARGE_EFFICIENCY = "charge_efficiency"
CONF_DISCHARGE_EFFICIENCY = "discharge_efficiency"
CONF_DEGRADATION_EUR_KWH = "degradation_eur_kwh"
CONF_HORIZON_HOURS = "horizon_hours"
CONF_STEP_MINUTES = "step_minutes"
CONF_OPTIMIZE_INTERVAL_MIN = "optimize_interval_min"
CONF_EXPORT_PRICE_EUR_KWH = "export_price_eur_kwh"
CONF_MODE = "mode"
CONF_ENABLE_CONTROL = "enable_control"

# InfluxDB hourly price source (optional; uses the influxdb config entry)
CONF_INFLUX_PRICES_ENABLED = "influx_prices_enabled"
CONF_INFLUX_BUCKET = "influx_bucket"
CONF_INFLUX_IMPORT_MEASUREMENT = "influx_import_measurement"
CONF_INFLUX_IMPORT_FIELD = "influx_import_field"
CONF_INFLUX_EXPORT_MEASUREMENT = "influx_export_measurement"
CONF_INFLUX_EXPORT_FIELD = "influx_export_field"

# Default measurement names of the audited ree_indicators bucket (GTS)
DEFAULT_INFLUX_BUCKET = "ree_indicators"
DEFAULT_INFLUX_IMPORT_MEASUREMENT = "precio_consumo_kwh"
DEFAULT_INFLUX_EXPORT_MEASUREMENT = "precio_excedentes_kwh"

# ---------------------------------------------------------------------------
# Operating modes
# ---------------------------------------------------------------------------
MODE_AUTO = "auto"
MODE_SHADOW = "shadow"
MODE_SOLAR_PRIORITY = "solar_priority"
MODE_ECONOMIC = "economic"
MODE_BACKUP = "backup"
MODE_MANUAL = "manual"
MODE_SAFE = "safe"

MODES: tuple[str, ...] = (
    MODE_SHADOW,
    MODE_MANUAL,
    MODE_SAFE,
    MODE_SOLAR_PRIORITY,
    MODE_ECONOMIC,
    MODE_BACKUP,
    MODE_AUTO,
)

# Modes allowed to issue control orders (still require CONF_ENABLE_CONTROL)
CONTROL_MODES: frozenset[str] = frozenset(
    {MODE_AUTO, MODE_SOLAR_PRIORITY, MODE_ECONOMIC, MODE_BACKUP}
)

DEFAULT_MODE = MODE_SHADOW

# ---------------------------------------------------------------------------
# Defaults audited on GTS Solutions (see docs/ENTITY_AUDIT.md)
# ---------------------------------------------------------------------------
DEFAULT_PV_POWER_ENTITY = (
    "sensor.garaje_deye_sun_15k_sg05lp3_eu_sm2_microinverter_power"
)
DEFAULT_GRID_POWER_ENTITY = "sensor.deye_sun_15k_sg05lp3_eu_sm2_external_power"
DEFAULT_LOAD_POWER_ENTITY = "sensor.deye_sun_15k_sg05lp3_eu_sm2_load_ups_power"
DEFAULT_BATTERY_SOC_ENTITY = "sensor.deye_sun_15k_sg05lp3_eu_sm2_battery"
DEFAULT_BATTERY_POWER_ENTITY = "sensor.deye_sun_15k_sg05lp3_eu_sm2_battery_power"
DEFAULT_PRICE_IMPORT_ENTITY = "sensor.esios_pvpc"
DEFAULT_PV_FORECAST_ENTITY = "sensor.energy_production_today"
DEFAULT_PV_FORECAST_TOMORROW_ENTITY = "sensor.energy_production_tomorrow"
DEFAULT_PV_PEAK_TODAY_ENTITY = "sensor.power_highest_peak_time_today"
DEFAULT_PV_PEAK_TOMORROW_ENTITY = "sensor.power_highest_peak_time_tomorrow"
DEFAULT_ENERGY_IMPORT_ENTITY = (
    "sensor.deye_sun_15k_sg05lp3_eu_sm2_total_energy_import"
)
DEFAULT_ENERGY_EXPORT_ENTITY = (
    "sensor.deye_sun_15k_sg05lp3_eu_sm2_total_energy_export"
)

# ---------------------------------------------------------------------------
# Parameter defaults (see docs/CONFIGURATION.md)
# ---------------------------------------------------------------------------
DEFAULT_BATTERY_USABLE_KWH = 30.0
DEFAULT_SOC_MIN_PCT = 20.0
DEFAULT_SOC_MAX_PCT = 95.0
DEFAULT_RESERVE_SOC_PCT = 35.0
DEFAULT_MAX_CHARGE_W = 5300.0
DEFAULT_MAX_DISCHARGE_W = 6300.0
DEFAULT_CHARGE_EFFICIENCY = 0.95
DEFAULT_DISCHARGE_EFFICIENCY = 0.95
DEFAULT_DEGRADATION_EUR_KWH = 0.02
DEFAULT_HORIZON_HOURS = 24
DEFAULT_STEP_MINUTES = 60
DEFAULT_OPTIMIZE_INTERVAL_MIN = 15
DEFAULT_EXPORT_PRICE_EUR_KWH = 0.14

# Coordinator
UPDATE_INTERVAL_S = 60
MAX_SNAPSHOT_AGE_S = 900
