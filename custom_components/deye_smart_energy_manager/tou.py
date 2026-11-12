"""Read-only interpretation of the Deye time-of-use (TOU) charge programs.

The inverter exposes 6 daily programs, each with a start time and a
charging source (``Disabled`` / ``Grid`` / ``Generator`` / ``Both``).
Program *i* governs the window from its start time until the next
program's start time (wrapping past midnight).

DSEM only *reads* these entities for diagnostics: the grid-charging
switch remains the single control surface once the user opens the TOU
windows (see docs/CONFIGURATION.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Charging-source values that permit energy from the grid.
_GRID_SOURCES = frozenset({"grid", "both"})


def program_windows(
    program_states: list[str | None],
    program_times: list[str | None],
) -> list[tuple[int, str]]:
    """Merge the 6 TOU programs into (start_minute, source) windows.

    ``program_times`` are "HH:MM[:SS]" strings; invalid/missing entries
    are dropped. Windows are sorted by start minute and de-duplicated
    (last program wins on ties, matching sequential overwrite).
    """
    windows: dict[int, str] = {}
    for state, hhmm in zip(program_states, program_times):
        if state is None or hhmm is None:
            continue
        try:
            hh, mm = (int(p) for p in hhmm.split(":")[:2])
        except (ValueError, AttributeError):
            continue
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            windows[hh * 60 + mm] = state.strip().lower()
    return sorted(windows.items())


def source_at(windows: list[tuple[int, str]], minute_of_day: int) -> str | None:
    """Charging source governing ``minute_of_day`` (0-1439).

    Windows wrap past midnight: minutes before the first program start
    belong to the last program of the day.
    """
    if not windows:
        return None
    source = windows[-1][1]  # wrap-around: last program covers the dawn
    for start, src in windows:
        if start <= minute_of_day:
            source = src
        else:
            break
    return source


def grid_charge_allowed_hours(
    windows: list[tuple[int, str]],
    first_hour: datetime,
    horizon: int,
) -> list[bool]:
    """Per-slot flag: is grid charging permitted by the TOU program?"""
    out: list[bool] = []
    for i in range(horizon):
        dt = first_hour + timedelta(hours=i)
        minute = dt.hour * 60 + dt.minute
        src = source_at(windows, minute)
        out.append(src in _GRID_SOURCES if src is not None else True)
    return out
