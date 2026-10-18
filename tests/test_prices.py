"""Unit tests for the PVPC price series parser."""
from __future__ import annotations

from datetime import datetime

from dsem.prices import build_price_series, series_from_points

NOW = datetime(2026, 10, 18, 14, 32)


def _attrs(base=0.10, next_day=False):
    attrs = {f"price_{h:02d}h": base + h / 1000 for h in range(24)}
    if next_day:
        attrs.update(
            {f"price_next_day_{h:02d}h": base + 0.5 + h / 1000 for h in range(24)}
        )
    return attrs


def test_today_hours_aligned_and_known():
    s = build_price_series(_attrs(), NOW, 24)
    assert s.first_hour == datetime(2026, 10, 18, 14, 0)
    assert s.prices[0] == 0.114  # price_14h
    assert s.prices[9] == 0.123  # price_23h


def test_tomorrow_missing_when_not_published():
    s = build_price_series(_attrs(), NOW, 24)
    # Hours 10-23 of the series are tomorrow -> unknown.
    assert all(p is None for p in s.prices[10:])
    assert s.missing_hours == 14


def test_next_day_attributes_fill_tomorrow():
    s = build_price_series(_attrs(next_day=True), NOW, 24)
    assert s.prices[10] == 0.600  # next_day price_00h
    assert s.missing_hours == 0


def test_filled_uses_nearest_known():
    s = build_price_series(_attrs(), NOW, 24).filled()
    assert s.missing_hours == 0
    # Backward fill: tomorrow inherits today's last known hour (23h).
    assert s.prices[10] == s.prices[9]


def test_empty_attributes_all_none():
    s = build_price_series({}, NOW, 24)
    assert s.known == ()
    assert s.missing_hours == 24


def test_series_from_points_aligns_hours():
    first = datetime(2026, 10, 18, 14, 0)
    points = {
        datetime(2026, 10, 18, 14, 12): 0.10,   # floors to 14:00
        datetime(2026, 10, 18, 16, 55): 0.30,   # floors to 16:00
    }
    s = series_from_points(points, first, 4)
    assert s == (0.10, None, 0.30, None)


def test_series_from_points_utc_to_local():
    from datetime import timezone, timedelta

    first = datetime(2026, 10, 18, 14, 0)  # naive = same-tz as points
    # A UTC point at 12:00 maps to 14:00 local (+02:00 CEST).
    points = {
        datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc): 0.20,
    }
    local_tz = timezone(timedelta(hours=2))
    first = first.replace(tzinfo=local_tz)
    s = series_from_points(points, first, 2)
    assert s[0] == 0.20
    assert s[1] is None
