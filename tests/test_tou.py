"""Unit tests for TOU program window interpretation."""
from __future__ import annotations

from datetime import datetime

from dsem.tou import (
    grid_charge_allowed_hours,
    program_windows,
    source_at,
)

# Mirrors the live inverter: programs at 01/05/09/13/17/21,
# Disabled in the morning, Grid in the afternoon/night.
STATES = ["Disabled"] * 3 + ["Grid"] * 3
TIMES = ["01:00", "05:00", "09:00", "13:00", "17:00", "21:00"]


def test_program_windows_sorted():
    windows = program_windows(STATES, TIMES)
    assert windows == [
        (60, "disabled"), (300, "disabled"), (540, "disabled"),
        (780, "grid"), (1020, "grid"), (1260, "grid"),
    ]


def test_source_at_wraps_midnight():
    windows = program_windows(STATES, TIMES)
    assert source_at(windows, 0) == "grid"       # 00:xx -> program 6
    assert source_at(windows, 60) == "disabled"  # 01:00 -> program 1
    assert source_at(windows, 720) == "disabled"  # 12:00 -> program 3
    assert source_at(windows, 800) == "grid"     # 13:20 -> program 4
    assert source_at(windows, 1380) == "grid"    # 23:00 -> program 6


def test_grid_charge_allowed_hours():
    windows = program_windows(STATES, TIMES)
    first = datetime(2026, 11, 12, 10, 0)
    allowed = grid_charge_allowed_hours(windows, first, 24)
    # 10:00-12:59 blocked (program 3), 13:00+ allowed (program 4).
    assert allowed[0] is False   # 10:00
    assert allowed[2] is False   # 12:00
    assert allowed[3] is True    # 13:00
    assert allowed[10] is True   # 20:00
    # Next day 00:00-00:59 still program 6 -> allowed; 01:00 blocked.
    assert allowed[14] is True   # next-day 00:00
    assert allowed[15] is False  # next-day 01:00


def test_both_counts_as_grid_source():
    windows = program_windows(["Both"] * 6, TIMES)
    assert source_at(windows, 120) == "both"
    allowed = grid_charge_allowed_hours(
        windows, datetime(2026, 11, 12, 3, 0), 2
    )
    assert all(allowed)


def test_invalid_entries_dropped():
    windows = program_windows(
        ["Grid", None, "bogus_state", "Disabled"],
        ["25:99", "09:00", "13:00", None],
    )
    assert windows == [(780, "bogus_state")]
    assert source_at(windows, 800) == "bogus_state"
    # Unknown source is not a grid source -> blocked.
    allowed = grid_charge_allowed_hours(
        windows, datetime(2026, 11, 12, 13, 30), 1
    )
    assert allowed == [False]
