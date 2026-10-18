"""DataUpdateCoordinator for Deye Smart Energy Manager."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
    CONF_INFLUX_PRICES_ENABLED,
    CONF_LOAD_POWER_ENTITY,
    CONF_MAX_CHARGE_W,
    CONF_MAX_DISCHARGE_W,
    CONF_MODE,
    CONF_PRICE_IMPORT_ENTITY,
    CONF_PV_FORECAST_ENTITY,
    CONF_PV_FORECAST_TOMORROW_ENTITY,
    CONF_PV_PEAK_TODAY_ENTITY,
    CONF_PV_PEAK_TOMORROW_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_RESERVE_SOC_PCT,
    CONF_SOC_MAX_PCT,
    CONF_SOC_MIN_PCT,
    DEFAULT_BATTERY_USABLE_KWH,
    DEFAULT_CHARGE_EFFICIENCY,
    DEFAULT_DEGRADATION_EUR_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY,
    DEFAULT_EXPORT_PRICE_EUR_KWH,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_MAX_CHARGE_W,
    DEFAULT_MAX_DISCHARGE_W,
    DEFAULT_MODE,
    DEFAULT_RESERVE_SOC_PCT,
    DEFAULT_SOC_MAX_PCT,
    DEFAULT_SOC_MIN_PCT,
    DOMAIN,
    MAX_SNAPSHOT_AGE_S,
    UPDATE_INTERVAL_S,
)
from .forecast import (
    async_load_statistics,
    build_load_series,
    build_pv_series,
)
from .influx import async_query_hourly_prices, get_influx_settings
from .model import EnergyPlan, EnergySnapshot
from .optimizer import BatteryParams, PlannerInput, optimize
from .prices import build_price_series, series_from_points

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
        self.plan: EnergyPlan | None = None
        self.plan_meta: dict[str, str] = {}

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

    def _datetime(self, entity_id: str | None) -> datetime | None:
        """Read a timestamp/datetime-valued sensor."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state.lower() in _UNAVAIL:
            return None
        return dt_util.parse_datetime(state.state)

    # -- planning -----------------------------------------------------------

    async def _async_build_plan(
        self, snapshot: EnergySnapshot
    ) -> EnergyPlan | None:
        """Assemble hourly series and run the planner (SHADOW-safe).

        Never raises: a planning failure only degrades the plan, never
        the snapshot update.
        """
        opts = self._entry.options
        data = self._entry.data
        now = dt_util.now()  # local tz — PVPC hours are local
        horizon = int(opts.get(CONF_HORIZON_HOURS, DEFAULT_HORIZON_HOURS))
        try:
            price_state = self.hass.states.get(
                data.get(CONF_PRICE_IMPORT_ENTITY)
            )
            price_series = build_price_series(
                dict(price_state.attributes) if price_state else {},
                now,
                horizon,
            )
            load_means = await async_load_statistics(
                self.hass, data.get(CONF_LOAD_POWER_ENTITY)
            )
            load = build_load_series(now, horizon, load_means)
            pv = build_pv_series(
                now,
                horizon,
                snapshot.pv_forecast_today_kwh,
                snapshot.pv_forecast_tomorrow_kwh,
                self._datetime(data.get(CONF_PV_PEAK_TODAY_ENTITY)),
                self._datetime(data.get(CONF_PV_PEAK_TOMORROW_ENTITY)),
            )
            import_prices = price_series.prices
            export_prices = None
            self.plan_meta = {
                "load_source": load.source,
                "pv_source": pv.source,
                "price_source": "pvpc",
                "price_missing_hours": str(price_series.missing_hours),
            }
            if opts.get(CONF_INFLUX_PRICES_ENABLED, True):
                influx = await self._async_influx_prices(
                    now, horizon, price_series.first_hour
                )
                if influx is not None:
                    imp, exp, meta = influx
                    self.plan_meta.update(meta)
                    if any(v is not None for v in imp):
                        import_prices = tuple(
                            i if i is not None else p
                            for i, p in zip(imp, price_series.prices)
                        )
                        self.plan_meta["price_source"] = "influxdb"
                    if any(v is not None for v in exp):
                        export_prices = exp
            soc = snapshot.battery_soc_pct
            reserve = float(
                opts.get(CONF_RESERVE_SOC_PCT, DEFAULT_RESERVE_SOC_PCT)
            )
            battery = BatteryParams(
                usable_kwh=float(
                    opts.get(
                        CONF_BATTERY_USABLE_KWH, DEFAULT_BATTERY_USABLE_KWH
                    )
                ),
                soc_pct=soc if soc is not None else reserve,
                soc_min_pct=float(
                    opts.get(CONF_SOC_MIN_PCT, DEFAULT_SOC_MIN_PCT)
                ),
                soc_max_pct=float(
                    opts.get(CONF_SOC_MAX_PCT, DEFAULT_SOC_MAX_PCT)
                ),
                reserve_pct=reserve,
                max_charge_w=float(
                    opts.get(CONF_MAX_CHARGE_W, DEFAULT_MAX_CHARGE_W)
                ),
                max_discharge_w=float(
                    opts.get(CONF_MAX_DISCHARGE_W, DEFAULT_MAX_DISCHARGE_W)
                ),
                charge_efficiency=float(
                    opts.get(CONF_CHARGE_EFFICIENCY, DEFAULT_CHARGE_EFFICIENCY)
                ),
                discharge_efficiency=float(
                    opts.get(
                        CONF_DISCHARGE_EFFICIENCY, DEFAULT_DISCHARGE_EFFICIENCY
                    )
                ),
                degradation_eur_kwh=float(
                    opts.get(
                        CONF_DEGRADATION_EUR_KWH, DEFAULT_DEGRADATION_EUR_KWH
                    )
                ),
            )
            plan = optimize(
                PlannerInput(
                    first_hour=price_series.first_hour,
                    import_prices=price_series.prices,
                    export_price_eur_kwh=float(
                        opts.get(
                            CONF_EXPORT_PRICE_EUR_KWH,
                            DEFAULT_EXPORT_PRICE_EUR_KWH,
                        )
                    ),
                    pv_kw=pv.kw,
                    load_kw=load.kw,
                    battery=battery,
                    export_prices=export_prices,
                )
            )
            if soc is None:
                plan = replace(
                    plan, warnings=plan.warnings + ("soc_unknown",)
                )
            return plan
        except Exception as err:  # noqa: BLE001 - planning must not break updates
            _LOGGER.warning("DSEM plan computation failed: %s", err)
            self.plan_meta = {}
            return None

    async def _async_influx_prices(
        self, now: datetime, horizon: int, first_hour: datetime
    ) -> tuple[tuple, tuple, dict] | None:
        """Hourly import/export prices from the REE indicators bucket.

        Returns aligned (import, export, meta) tuples, or None when the
        source is unavailable/misconfigured.
        """
        settings = get_influx_settings(self.hass, self._entry.options)
        if settings is None or not settings.bucket:
            return None
        result = await async_query_hourly_prices(
            self.hass, settings, now, horizon
        )
        if result is None:
            return None
        imp_pts, exp_pts, meta = result
        imp = series_from_points(imp_pts, first_hour, horizon)
        exp = series_from_points(exp_pts, first_hour, horizon)
        return imp, exp, meta

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
        self.plan = await self._async_build_plan(snapshot)
        return snapshot
