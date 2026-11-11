"""Unit tests for the synthesized forecast series."""
from __future__ import annotations

from datetime import datetime

from dsem.forecast import (
    _quantile,
    build_load_series,
    build_pv_series,
    pv_bias,
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


def test_quantile_interpolates():
    assert _quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert abs(_quantile([2.0, 2.0, 4.5, 4.4, 4.3], 0.7) - 4.38) < 0.001
    assert _quantile([7.0], 0.9) == 7.0


def test_rows_to_hourly_means_uses_quantile():
    """P70 of an hour that usually has EV charging keeps the peak."""
    rows = [
        {"start": datetime(2026, 10, 10, 19, 0), "mean": 2.0},
        {"start": datetime(2026, 10, 11, 19, 0), "mean": 4.5},
        {"start": datetime(2026, 10, 12, 19, 0), "mean": 4.3},
        {"start": datetime(2026, 10, 13, 19, 0), "mean": 4.4},
        {"start": datetime(2026, 10, 14, 19, 0), "mean": 2.0},
    ]
    out = rows_to_hourly_means(rows, quantile=0.70)
    assert out[19] > 4.0  # P70 picks the powered state, not the 2.6 mean
    out_med = rows_to_hourly_means(rows, quantile=0.5)
    assert abs(out_med[19] - 4.3) < 0.2  # median = middle sample


def test_load_series_nowcast_decays():
    means = {h: 2.0 for h in range(24)}
    s = build_load_series(NOW, 24, hourly_means=means, nowcast_kw=1.0)
    assert abs(s.kw[0] - 3.0) < 0.01          # full residual hour 0
    assert abs(s.kw[1] - 2.6) < 0.01          # decays 0.6^1
    assert s.kw[6] == 2.0                      # gone after 6 h
    assert "+nowcast" in s.source


def test_load_series_ev_boost_floor():
    means = {h: 2.0 for h in range(24)}  # base floor 2 kW (servers)
    s = build_load_series(
        NOW, 24, hourly_means=means, ev_boost_kw=2.3, ev_boost_hours=3
    )
    for i in range(3):
        assert abs(s.kw[i] - 4.3) < 0.01  # base + EV estimate
    assert s.kw[3] == 2.0
    assert "+ev_live" in s.source


def test_pv_bias_clamps_and_scales():
    # noon on a sunny day: ~half the bell elapsed; realized = 2x expected
    noon = datetime(2026, 10, 18, 14, 0)
    b = pv_bias(today_kwh=10.0, realized_kwh=10.0, now=noon)
    assert b == 1.5                          # clamped at hi
    b = pv_bias(today_kwh=10.0, realized_kwh=0.1, now=noon)
    assert b == 0.5                          # clamped at lo
    # too early: expected fraction ~0 -> neutral
    early = datetime(2026, 10, 18, 7, 0)
    assert pv_bias(today_kwh=10.0, realized_kwh=0.0, now=early) == 1.0
    # no forecast -> neutral
    assert pv_bias(None, 5.0, now=noon) == 1.0


def test_pv_series_applies_bias():
    s = build_pv_series(NOW, 48, today_kwh=10.0, tomorrow_kwh=10.0, bias=1.3)
    day1 = sum(s.kw[15:])  # full tomorrow (starts at idx 24-9=15)
    assert abs(day1 - 13.0) < 1.0
    s0 = build_pv_series(NOW, 48, today_kwh=10.0, tomorrow_kwh=10.0)
    assert abs(sum(s0.kw[15:]) - 10.0) < 0.5  # bias=1.0 unchanged
