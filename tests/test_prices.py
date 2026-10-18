"""Unit tests for the PVPC price series parser."""
from __future__ import annotations

from datetime import datetime

from dsem.prices import build_price_series

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
