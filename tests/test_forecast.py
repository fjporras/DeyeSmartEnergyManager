"""Unit tests for the synthesized forecast series."""
from __future__ import annotations

from datetime import datetime

from dsem.forecast import (
    build_load_series,
    build_pv_series,
    rows_to_hourly_means,
)

NOW = datetime(2026, 10, 18, 9, 0)


def test_pv_series_sums_to_daily_totals():
    s = build_pv_series(NOW, 48, today_kwh=15.0, tomorrow_kwh=12.0)
    assert len(s.kw) == 48
    day0 = sum(s.kw[:15])   # today: only hours 09-23 remain
    day1 = sum(s.kw[15:])   # tomorrow: full day
    assert day0 < 15.0 and day0 > 10.0  # morning already elapsed
    assert abs(day1 - 12.0) < 0.5


def test_pv_series_night_hours_are_zero():
    s = build_pv_series(NOW, 48, today_kwh=10.0, tomorrow_kwh=10.0)
    # Today starts at 09:00; tomorrow's 00-05 sit at idx 15-19 and its
    # 22-23 at idx 37-38.
    for i in (15, 16, 17, 18, 19, 37, 38):
        assert s.kw[i] == 0.0


def test_pv_series_no_forecast_is_zero():
    s = build_pv_series(NOW, 24, today_kwh=None, tomorrow_kwh=None)
    assert all(v == 0.0 for v in s.kw)


def test_load_series_fallback_profile():
    s = build_load_series(NOW, 24, hourly_means=None, recent_daily_kwh=60.0)
    assert len(s.kw) == 24
    assert all(v >= 0 for v in s.kw)
    assert s.source == "fallback_profile"
    # Profile is scaled to ~60 kWh/day.
    assert abs(sum(s.kw) - 60.0) < 1.0


def test_load_series_uses_recorder_means():
    means = {h: 3.0 for h in range(24)}
    s = build_load_series(NOW, 24, hourly_means=means)
    assert s.source == "recorder_statistics"
    assert all(v == 3.0 for v in s.kw)


def test_rows_to_hourly_means_accepts_epoch_start():
    """Regression: HA >= 2026 returns 'start' as epoch float."""
    epoch = datetime(2026, 10, 17, 14, 0).timestamp()
    rows = [{"start": epoch, "mean": 2300.0},
            {"start": epoch + 3600, "mean": 2500.0}]
    out = rows_to_hourly_means(rows)
    assert out is not None
    assert abs(sum(out.values())) < 0.001 + 4.8  # W -> kW conversion


def test_rows_to_hourly_means_accepts_datetime_start():
    rows = [{"start": datetime(2026, 10, 17, 14, 0), "mean": 2.3}]
    out = rows_to_hourly_means(rows)
    assert out == {14: 2.3}


def test_rows_to_hourly_means_empty():
    assert rows_to_hourly_means([]) is None
    assert rows_to_hourly_means([{"start": 1.0, "mean": None}]) is None
