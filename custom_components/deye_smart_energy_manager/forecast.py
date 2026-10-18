"""Load and PV forecast series for the planner.

Pure helpers live at module level (unit-testable). The Recorder reader is
imported lazily inside ``async_load_statistics`` so this module can be
imported without Home Assistant.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)

# Fallback hourly load profile (relative weights, ES residential shape):
# night valley, morning ramp, midday dip, evening peak 19-23h.
_FALLBACK_LOAD_PROFILE: tuple[float, ...] = (
    0.55, 0.50, 0.48, 0.47, 0.48, 0.55,  # 00-05
    0.80, 1.00, 1.05, 0.95, 0.85, 0.80,  # 06-11
    0.85, 0.95, 1.00, 0.85, 0.75, 0.75,  # 12-17
    0.95, 1.25, 1.45, 1.50, 1.40, 1.10,  # 18-23
)


@dataclass(frozen=True)
class HourlySeries:
    """Hour-aligned forecast in kW (mean power during each hour)."""

    first_hour: datetime
    kw: tuple[float, ...]
    source: str  # explainability: where the numbers came from


def _hour_floor(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def build_load_series(
    now: datetime,
    horizon_hours: int,
    hourly_means: dict[int, float] | None = None,
    recent_daily_kwh: float | None = None,
) -> HourlySeries:
    """Forecast load (kW) per hour for the horizon.

    ``hourly_means``: recorder-derived mean kW per hour-of-day (0-23).
    ``recent_daily_kwh``: mean daily consumption used to scale the
    fallback profile when no hourly history exists.
    """
    first = _hour_floor(now)
    profile = _FALLBACK_LOAD_PROFILE
    if hourly_means:
        profile = tuple(hourly_means.get(h, _FALLBACK_LOAD_PROFILE[h]) for h in range(24))
        source = "recorder_statistics"
    else:
        # Scale fallback to the recent daily energy (default 45 kWh/day,
        # audited GTS mean is ~55-90 kWh/day so this errs low).
        daily = recent_daily_kwh if recent_daily_kwh else 45.0
        scale = daily / sum(_FALLBACK_LOAD_PROFILE)
        profile = tuple(w * scale for w in _FALLBACK_LOAD_PROFILE)
        source = "fallback_profile"
    kw = tuple(max(0.0, profile[(first + timedelta(hours=i)).hour])
               for i in range(horizon_hours))
    return HourlySeries(first, kw, source)


def build_pv_series(
    now: datetime,
    horizon_hours: int,
    today_kwh: float | None,
    tomorrow_kwh: float | None,
    peak_today: datetime | None = None,
    peak_tomorrow: datetime | None = None,
) -> HourlySeries:
    """Synthesize the hourly PV curve (kW) from daily totals.

    forecast_solar does not expose its per-hour vector, so we distribute
    the daily energy on a Gaussian bell centered on the reported peak
    time (default 14:00 local). Elapsed hours of today are set to 0
    beyond ``now`` — history correction is a later refinement.
    """
    first = _hour_floor(now)
    sigma = 3.0
    kw: list[float] = []
    for i in range(horizon_hours):
        hour = first + timedelta(hours=i)
        day = (hour.date() - now.date()).days
        if day == 0:
            total, peak = today_kwh, peak_today
        elif day == 1:
            total, peak = tomorrow_kwh, peak_tomorrow
        else:
            total, peak = None, None
        if not total:
            kw.append(0.0)
            continue
        peak_hour = peak.hour + peak.minute / 60 if peak else 14.0
        mid = hour.hour + 0.5
        weight = math.exp(-0.5 * ((mid - peak_hour) / sigma) ** 2)
        # Normalize the bell over daylight hours so the day sums `total`.
        norm = sum(
            math.exp(-0.5 * ((h + 0.5 - peak_hour) / sigma) ** 2)
            for h in range(6, 22)
        )
        kw.append(round(total * weight / norm, 4) if 6 <= hour.hour < 22 else 0.0)
    return HourlySeries(first, tuple(kw), "forecast_solar_daily+bell")


async def async_load_statistics(
    hass, statistic_id: str, days: int = 14
) -> dict[int, float] | None:
    """Return mean kW per hour-of-day from Recorder statistics.

    ``None`` when Recorder or the statistic is unavailable. Runs in the
    recorder executor; never raises — forecasts degrade gracefully.
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )
        from homeassistant.util import dt as dt_util
    except ImportError:
        return None

    end = dt_util.utcnow()
    start = end - timedelta(days=days)
    try:
        stats = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            start,
            end,
            {statistic_id},
            "hour",
            None,
            {"mean"},
        )
    except Exception as err:  # noqa: BLE001 - degrade, never break updates
        _LOGGER.debug("DSEM recorder statistics failed: %s", err)
        return None
    rows = (stats or {}).get(statistic_id) or []
    if not rows:
        return None
    return rows_to_hourly_means(rows, _epoch_to_local_hour)


def _epoch_to_local_hour(epoch: float) -> int:
    """Epoch seconds -> local hour-of-day (uses HA's tz)."""
    from homeassistant.util import dt as dt_util

    return dt_util.as_local(dt_util.utc_from_timestamp(epoch)).hour


def rows_to_hourly_means(
    rows: list[dict], epoch_to_hour=None
) -> dict[int, float] | None:
    """Reduce recorder statistic rows to {hour_of_day: mean kW}.

    ``epoch_to_hour`` converts epoch seconds to a local hour; defaults to
    a UTC-based fallback for offline testing. Rows may carry ``start``
    as a datetime (older HA) or an epoch float (HA >= 2026).
    """
    if epoch_to_hour is None:
        epoch_to_hour = lambda ts: datetime.utcfromtimestamp(  # noqa: E731
            float(ts)
        ).hour

    sums: dict[int, list[float]] = {}
    for row in rows:
        mean = row.get("mean")
        start = row.get("start")
        if mean is None or start is None:
            continue
        if isinstance(start, (int, float)):
            hour = epoch_to_hour(start)
        else:
            hour = start.hour
        sums.setdefault(hour, []).append(float(mean))
    if not sums:
        return None
    # Watts -> kW if the statistic is in W (heuristic: values > 50 are W
    # for a house-load sensor; load_power is natively W on solarman).
    out = {h: sum(v) / len(v) for h, v in sums.items()}
    if max(out.values()) > 50:
        out = {h: v / 1000.0 for h, v in out.items()}
    return out
