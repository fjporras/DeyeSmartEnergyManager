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
    nowcast_kw: float = 0.0,
    nowcast_hours: int = 6,
    ev_boost_kw: float = 0.0,
    ev_boost_hours: int = 4,
) -> HourlySeries:
    """Forecast load (kW) per hour for the horizon.

    ``hourly_means``: recorder-derived profile per hour-of-day (0-23)
    (a quantile, typically P70, not the mean — so recurring peaks are
    not diluted). ``nowcast_kw`` is a residual correction (actual minus
    profile over the last hours) persisted with exponential decay; it
    absorbs slow drifts the static profile misses. ``ev_boost_kw`` is an
    explicit EV-charging floor for the next ``ev_boost_hours`` hours: a
    charging session detected live is guaranteed in the forecast even
    when the statistical profile is below it.
    """
    first = _hour_floor(now)
    profile = _FALLBACK_LOAD_PROFILE
    source = "fallback_profile"
    if hourly_means:
        profile = tuple(hourly_means.get(h, _FALLBACK_LOAD_PROFILE[h]) for h in range(24))
        source = "recorder_statistics"
    else:
        daily = recent_daily_kwh if recent_daily_kwh else 45.0
        scale = daily / sum(_FALLBACK_LOAD_PROFILE)
        profile = tuple(w * scale for w in _FALLBACK_LOAD_PROFILE)
    base = min(profile)  # ~server/base floor used under the EV boost
    kw: list[float] = []
    for i in range(horizon_hours):
        v = profile[(first + timedelta(hours=i)).hour]
        if i < nowcast_hours:
            v += nowcast_kw * (0.6 ** i)
        if ev_boost_kw > 0 and i < ev_boost_hours:
            v = max(v, base + ev_boost_kw)
        kw.append(max(0.0, v))
    if ev_boost_kw > 0:
        source += "+ev_live"
    elif nowcast_kw:
        source += "+nowcast"
    return HourlySeries(first, tuple(kw), source)


def build_pv_series(
    now: datetime,
    horizon_hours: int,
    today_kwh: float | None,
    tomorrow_kwh: float | None,
    peak_today: datetime | None = None,
    peak_tomorrow: datetime | None = None,
    bias: float = 1.0,
) -> HourlySeries:
    """Synthesize the hourly PV curve (kW) from daily totals.

    forecast_solar does not expose its per-hour vector, so we distribute
    the daily energy on a Gaussian bell centered on the reported peak
    time (default 14:00 local). ``bias`` scales the daily total with the
    rolling correction factor (see ``pv_bias``) — validation showed the
    shape is right but the raw scale errs ±50%. Elapsed hours of today
    are set to 0 beyond ``now``.
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
        total *= bias
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


def pv_bias(
    today_kwh: float | None,
    realized_kwh: float,
    now: datetime,
    peak: datetime | None = None,
    lo: float = 0.5,
    hi: float = 1.5,
) -> float:
    """Rolling correction factor for the forecast_solar scale.

    Compares realized PV energy so far today against the fraction of the
    daily forecast the bell curve attributes to elapsed hours. Clamped
    to [``lo``, ``hi``] so one abnormal day cannot dominate; returns 1.0
    when the reference is too small to be meaningful (early morning,
    tiny forecast).
    """
    if not today_kwh or today_kwh < 0.5:
        return 1.0
    peak_hour = peak.hour + peak.minute / 60 if peak else 14.0
    sigma = 3.0
    norm = sum(
        math.exp(-0.5 * ((h + 0.5 - peak_hour) / sigma) ** 2)
        for h in range(6, 22)
    )
    elapsed = sum(
        math.exp(-0.5 * ((h + 0.5 - peak_hour) / sigma) ** 2)
        for h in range(6, min(now.hour, 22))
    )
    expected = today_kwh * elapsed / norm
    if expected < 0.5:  # too early / dark day: nothing reliable yet
        return 1.0
    return max(lo, min(hi, realized_kwh / expected))


async def _async_stats_rows(hass, statistic_id: str, days: float) -> list[dict] | None:
    """Raw hourly Recorder statistics rows for ``statistic_id``."""
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
    return (stats or {}).get(statistic_id) or None


async def async_load_statistics(
    hass, statistic_id: str, days: int = 14, quantile: float = 0.70
) -> dict[int, float] | None:
    """Return kW per hour-of-day from Recorder statistics.

    Uses a quantile (default P70) instead of the plain mean so that
    recurring peaks — EV sessions, server load — are not diluted by
    idle hours. ``None`` when Recorder or the statistic is unavailable;
    never raises — forecasts degrade gracefully.
    """
    rows = await _async_stats_rows(hass, statistic_id, days)
    if not rows:
        return None
    return rows_to_hourly_means(rows, _epoch_to_local_hour, quantile)


async def async_recent_load_residual(
    hass,
    statistic_id: str,
    hourly_means: dict[int, float] | None,
    hours: int = 3,
) -> float:
    """Short-term load residual (kW): actual minus profile, last hours.

    Compares the last ``hours`` of realized load statistics with the
    static profile for those same hours-of-day; the mean difference is
    the nowcast correction that ``build_load_series`` persists forward
    with decay. Returns 0.0 when unusable.
    """
    rows = await _async_stats_rows(hass, statistic_id, days=0.25)
    if not rows:
        return 0.0
    actuals = [float(r["mean"]) for r in rows if r.get("mean") is not None][-hours:]
    if not actuals:
        return 0.0
    if max(actuals) > 50:  # W -> kW heuristic, same as rows_to_hourly_means
        actuals = [a / 1000.0 for a in actuals]
    if not hourly_means:
        return 0.0
    try:
        from homeassistant.util import dt as dt_util
        starts = [
            dt_util.as_local(dt_util.utc_from_timestamp(float(r["start"]))).hour
            for r in rows if r.get("mean") is not None
        ][-hours:]
    except Exception:  # noqa: BLE001
        return 0.0
    diffs = [a - hourly_means.get(h, 0.0) for a, h in zip(actuals, starts)]
    return sum(diffs) / len(diffs)


async def async_pv_realized_kwh(hass, statistic_id: str) -> float | None:
    """Today's realized PV energy (kWh) from hourly power statistics."""
    rows = await _async_stats_rows(hass, statistic_id, days=1)
    if not rows:
        return None
    try:
        from homeassistant.util import dt as dt_util
        today = dt_util.now().date()
        total = 0.0
        for r in rows:
            if r.get("mean") is None or r.get("start") is None:
                continue
            if dt_util.as_local(dt_util.utc_from_timestamp(float(r["start"]))).date() != today:
                continue
            total += float(r["mean"])  # hourly mean W x 1 h = Wh
        return total / 1000.0
    except Exception:  # noqa: BLE001
        return None


def _epoch_to_local_hour(epoch: float) -> int:
    """Epoch seconds -> local hour-of-day (uses HA's tz)."""
    from homeassistant.util import dt as dt_util

    return dt_util.as_local(dt_util.utc_from_timestamp(epoch)).hour


def rows_to_hourly_means(
    rows: list[dict], epoch_to_hour=None, quantile: float = 0.70
) -> dict[int, float] | None:
    """Reduce recorder statistic rows to {hour_of_day: quantile kW}.

    ``quantile`` picks a high percentile of each hour's distribution
    (P70 by default) instead of the mean — with intermittent large loads
    the mean underestimates the typical powered state. ``epoch_to_hour``
    converts epoch seconds to a local hour; defaults to a UTC-based
    fallback for offline testing. Rows may carry ``start`` as a
    datetime (older HA) or an epoch float (HA >= 2026).
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
    out = {h: _quantile(v, quantile) for h, v in sums.items()}
    # Watts -> kW if the statistic is in W (heuristic: values > 50 are W
    # for a house-load sensor; load_power is natively W on solarman).
    if max(out.values()) > 50:
        out = {h: v / 1000.0 for h, v in out.items()}
    return out


def _quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile of ``values`` (no numpy needed)."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    i = int(pos)
    return s[i] + (s[i + 1] - s[i]) * (pos - i) if i + 1 < len(s) else s[i]
