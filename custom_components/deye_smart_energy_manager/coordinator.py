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
    CONF_EV_CURRENT_ENTITY,
    CONF_EV_STATE_ENTITY,
    CONF_EXPORT_PRICE_EUR_KWH,
    CONF_GRID_CHARGE_SWITCH_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_HORIZON_HOURS,
    CONF_INFLUX_PRICES_ENABLED,
    CONF_LOAD_POWER_ENTITY,
    CONF_LOAD_PROFILE_QUANTILE,
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
    DEFAULT_GRID_CHARGE_SWITCH_ENTITY,
    DEFAULT_CHARGE_EFFICIENCY,
    DEFAULT_DEGRADATION_EUR_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY,
    DEFAULT_EXPORT_PRICE_EUR_KWH,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_LOAD_PROFILE_QUANTILE,
    DEFAULT_MAX_CHARGE_W,
    DEFAULT_MAX_DISCHARGE_W,
    DEFAULT_MODE,
    DEFAULT_TARGET_TIME,
    MODE_TARGET_SOC,
    DEFAULT_RESERVE_SOC_PCT,
    DEFAULT_SOC_MAX_PCT,
    DEFAULT_SOC_MIN_PCT,
    DOMAIN,
    MAX_SNAPSHOT_AGE_S,
    UPDATE_INTERVAL_S,
)
from .forecast import (
    async_load_statistics,
    async_pv_realized_kwh,
    async_recent_load_residual,
    build_load_series,
    build_pv_series,
    pv_bias,
)
from .influx import async_query_hourly_prices, get_influx_settings
from .model import EnergyPlan, EnergySnapshot
from .optimizer import BatteryParams, PlannerInput, optimize
from .prices import build_price_series, series_from_points
from .targets import KEY_SOC, KEY_TIME, target_slot_index, target_store
from .tou import (
    active_program_index,
    grid_charge_allowed_hours,
    program_windows,
    source_at,
)

_LOGGER = logging.getLogger(__name__)

_REQUIRED = (
    CONF_PV_POWER_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_POWER_ENTITY,
    CONF_PRICE_IMPORT_ENTITY,
)

# Entities that update hourly or slower legitimately (price sensors
# refresh once per REE publication). They still count as "missing" when
# absent, but their age must not gate physical control writes.
_STALE_EXEMPT = frozenset({CONF_PRICE_IMPORT_ENTITY})

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
        self._last_plan_log: str | None = None
        # Control executor state (control.py)
        self._control_ready_at = dt_util.now() + timedelta(
            seconds=300
        )
        self._control_last_write: datetime | None = None
        self._control_backoff_until: datetime | None = None
        self._control_failures = 0

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

    def _ev_state(self, entity_id: str | None) -> str | None:
        """Raw EV charger state string (tuya_local, e.g. idle/charging)."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state.lower() in _UNAVAIL:
            return None
        return state.state

    def _ev_power_w(
        self, state_entity: str | None, current_entity: str | None
    ) -> float | None:
        """Estimated EV charge power in W.

        The dé EV Charger (tuya_local) exposes no power sensor; power is
        estimated as charge_current_A x 230 V, only while the charger
        reports an active session. Returns 0 when idle — the estimate is
        clearly labelled in plan_meta (not a measurement).
        """
        state = self._ev_state(state_entity)
        if state is None:
            return None
        if state.lower() not in ("charging", "charge", "cargando"):
            return 0.0
        missing: list[str] = []
        amps = self._float(current_entity, missing)
        if amps is None or amps <= 0:
            return None
        return amps * DEFAULT_EV_VOLTAGE

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
            load_quantile = float(
                opts.get(
                    CONF_LOAD_PROFILE_QUANTILE, DEFAULT_LOAD_PROFILE_QUANTILE
                )
            )
            load_means = await async_load_statistics(
                self.hass,
                data.get(CONF_LOAD_POWER_ENTITY),
                quantile=load_quantile,
            )
            nowcast = await async_recent_load_residual(
                self.hass, data.get(CONF_LOAD_POWER_ENTITY), load_means
            )
            ev_boost_kw = (
                snapshot.ev_power_w / 1000.0 if snapshot.ev_power_w else 0.0
            )
            load = build_load_series(
                now,
                horizon,
                load_means,
                nowcast_kw=nowcast,
                ev_boost_kw=ev_boost_kw,
            )
            peak_today = self._datetime(data.get(CONF_PV_PEAK_TODAY_ENTITY))
            realized = await async_pv_realized_kwh(
                self.hass, data.get(CONF_PV_POWER_ENTITY)
            )
            bias = pv_bias(
                snapshot.pv_forecast_today_kwh,
                realized or 0.0,
                now,
                peak_today,
            )
            pv = build_pv_series(
                now,
                horizon,
                snapshot.pv_forecast_today_kwh,
                snapshot.pv_forecast_tomorrow_kwh,
                peak_today,
                self._datetime(data.get(CONF_PV_PEAK_TOMORROW_ENTITY)),
                bias=bias,
            )
            import_prices = price_series.prices
            export_prices = None
            self.plan_meta = {
                "load_source": load.source,
                "load_quantile": str(load_quantile),
                "nowcast_kw": f"{nowcast:.2f}",
                "pv_source": pv.source,
                "pv_bias": f"{bias:.2f}",
                "pv_realized_today_kwh": (
                    f"{realized:.1f}" if realized is not None else "none"
                ),
                "ev_state": snapshot.ev_state or "none",
                "ev_power_w": (
                    f"{snapshot.ev_power_w:.0f}"
                    if snapshot.ev_power_w is not None
                    else "none"
                ),
                "price_source": "pvpc",
                "price_missing_hours": str(price_series.missing_hours),
            }
            if opts.get(CONF_INFLUX_PRICES_ENABLED, True):
                influx = await self._async_influx_prices(
                    now, horizon, price_series.first_hour
                )
                if influx is None:
                    self.plan_meta["influx_status"] = "no_entry_or_bucket"
                else:
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
            self.plan_meta.update(
                self._tou_diagnostics(price_series.first_hour, horizon)
            )
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
            self.plan_meta["price_missing_hours"] = str(
                sum(1 for p in import_prices if p is None)
            )
            target_soc_pct: float | None = None
            target_idx: int | None = None
            target_warn: str | None = None
            if self.mode == MODE_TARGET_SOC:
                store = target_store(self.hass, self._entry.entry_id)
                try:
                    target_soc_pct = float(store.get(KEY_SOC, 0.0))
                except (TypeError, ValueError):
                    target_soc_pct = None
                hhmm = str(store.get(KEY_TIME, DEFAULT_TARGET_TIME))
                self.plan_meta["soc_target_pct"] = (
                    f"{target_soc_pct:g}" if target_soc_pct else "unset"
                )
                self.plan_meta["soc_target_time"] = hhmm
                if target_soc_pct and target_soc_pct > 0:
                    target_idx = target_slot_index(
                        price_series.first_hour, horizon, hhmm, now
                    )
                    self.plan_meta["soc_target_slot"] = (
                        str(target_idx) if target_idx is not None else "none"
                    )
                    if target_idx is None:
                        target_warn = "soc_target_out_of_horizon"
                else:
                    target_warn = "soc_target_not_configured"
            plan = optimize(
                PlannerInput(
                    first_hour=price_series.first_hour,
                    import_prices=import_prices,
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
                    soc_target_pct=target_soc_pct,
                    target_idx=target_idx,
                )
            )
            if target_warn:
                plan = replace(
                    plan, warnings=plan.warnings + (target_warn,)
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

    def _tou_diagnostics(
        self, first_hour: datetime, horizon: int
    ) -> dict[str, str]:
        """Read the inverter TOU charge programs (diagnostics only).

        Derives the entity prefix from the configured grid-charge switch
        (``switch.<prefix>_battery_grid_charging``) and reads the six
        ``program_N_charging``/``program_N_time`` pairs. Never raises.
        """
        try:
            switch = self._entry.options.get(
                CONF_GRID_CHARGE_SWITCH_ENTITY,
                DEFAULT_GRID_CHARGE_SWITCH_ENTITY,
            )
            prefix = switch.split(".", 1)[-1]
            suffix = "_battery_grid_charging"
            if prefix.endswith(suffix):
                prefix = prefix[: -len(suffix)]
            states_sel = [
                self.hass.states.get(
                    f"select.{prefix}_program_{i}_charging"
                )
                for i in range(1, 7)
            ]
            times = [
                self.hass.states.get(
                    f"time.{prefix}_program_{i}_time"
                )
                for i in range(1, 7)
            ]
            socs = [
                self.hass.states.get(
                    f"number.{prefix}_program_{i}_soc"
                )
                for i in range(1, 7)
            ]
            if not any(s is not None for s in states_sel + times):
                return {"tou_status": "unavailable"}
            time_vals = [t.state if t is not None else None for t in times]
            windows = program_windows(
                [s.state if s is not None else None for s in states_sel],
                time_vals,
            )
            if not windows:
                return {"tou_status": "unavailable"}
            allowed = grid_charge_allowed_hours(windows, first_hour, horizon)
            now = dt_util.now()
            minute = now.hour * 60 + now.minute
            src_now = source_at(windows, minute)
            meta = {
                "tou_status": "ok",
                "tou_now": src_now or "unknown",
                "tou_grid_blocked_hours": str(
                    sum(1 for a in allowed if not a)
                ),
            }
            # Per-program SOC target: the inverter stops charging at this
            # level inside the window — a hidden cap for target_soc mode.
            idx = active_program_index(time_vals, minute)
            if idx is not None and idx < len(socs):
                st = socs[idx]
                if st is not None and st.state not in _UNAVAIL:
                    meta["tou_now_soc"] = st.state
            return meta
        except Exception:  # noqa: BLE001 - diagnostics must not break plans
            return {"tou_status": "error"}

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
            if key not in _STALE_EXEMPT:
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
            ev_state=self._ev_state(data.get(CONF_EV_STATE_ENTITY)),
            ev_power_w=self._ev_power_w(
                data.get(CONF_EV_STATE_ENTITY),
                data.get(CONF_EV_CURRENT_ENTITY),
            ),
            missing_entities=tuple(missing),
            stale_entities=tuple(stale),
        )
        if missing:
            _LOGGER.debug("DSEM snapshot incomplete, missing: %s", missing)
        self.plan = await self._async_build_plan(snapshot)
        if self.plan is not None:
            await self._async_log_plan(self.plan)
        from .control import async_apply_control

        control_state = await async_apply_control(
            self.hass, self._entry, self, snapshot
        )
        if control_state:
            self.plan_meta["control"] = control_state
        return snapshot

    async def _async_log_plan(self, plan: EnergyPlan) -> None:
        """Persist one plan snapshot per hour for SHADOW validation.

        Recorder history keeps entity states but NOT attributes, so the
        hourly slots would be lost. This appends a compact JSON line to
        ``config/deye_smart_energy_manager/plan_log.jsonl`` (once per
        hour, keyed by plan start) so predictions can be compared with
        real data at T+24h. Never raises; capped file growth is handled
        by rotation when the log exceeds ~2 MB.
        """
        key = plan.slots[0].start.isoformat() if plan.slots else None
        if key is None or key == self._last_plan_log:
            return
        self._last_plan_log = key
        import json
        record = {
            "logged_at": dt_util.now().isoformat(),
            "horizon_hours": plan.horizon_hours,
            "expected_cost_eur": plan.expected_cost_eur,
            "baseline_cost_eur": plan.baseline_cost_eur,
            "meta": dict(self.plan_meta),
            "slots": [
                {
                    "t": s.start.isoformat(),
                    "a": s.action,
                    "bw": round(s.battery_power_w),
                    "gw": round(s.grid_power_w),
                    "soc": round(s.soc_end_pct, 1),
                    "p": s.import_price_eur_kwh,
                }
                for s in plan.slots
            ],
        }
        try:
            path = self.hass.config.path(DOMAIN, "plan_log.jsonl")
            await self.hass.async_add_executor_job(self._append_plan_line, path, record)
        except Exception as err:  # noqa: BLE001 - logging must not break updates
            _LOGGER.debug("DSEM plan log write failed: %s", err)

    @staticmethod
    def _append_plan_line(path: str, record: dict) -> None:
        """Append one JSON line, rotating the file beyond ~2 MB."""
        import json
        import os

        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
