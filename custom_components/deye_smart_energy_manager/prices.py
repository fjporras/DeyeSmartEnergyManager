"""Hourly import-price series parsed from the PVPC sensor attributes.

Pure module: no Home Assistant imports, so it is unit-testable offline.

PVPC exposes today's hourly prices as attributes ``price_00h`` ..
``price_23h`` (EUR/kWh). Once ESIOS publishes tomorrow (~20:30), the
integration adds ``price_next_day_00h`` .. ``price_next_day_23h``.
This module tolerates both spellings and reports coverage gaps instead
of inventing prices.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

_PRICE_RE = re.compile(r"^price_(?:next_day_)?(\d{1,2})h$")


@dataclass(frozen=True)
class PriceSeries:
    """Hourly import prices aligned to hour boundaries.

    ``prices[i]`` is the EUR/kWh for the hour starting at
    ``first_hour + i hours``; ``None`` marks an unpublished/unknown hour.
    """

    first_hour: datetime
    prices: tuple[float | None, ...]

    @property
    def horizon_hours(self) -> int:
        return len(self.prices)

    @property
    def known(self) -> tuple[float, ...]:
        """Known (non-None) prices, in order."""
        return tuple(p for p in self.prices if p is not None)

    @property
    def missing_hours(self) -> int:
        return sum(1 for p in self.prices if p is None)

    def filled(self) -> "PriceSeries":
        """Return a copy with gaps filled by the nearest known price.

        Backward-fill first (tomorrow's unpublished prices inherit the
        same hour of today — the least-wrong guess), then forward-fill.
        """
        vals = list(self.prices)
        n = len(vals)
        for i in range(n - 1, -1, -1):  # backward
            if vals[i] is None and i + 1 < n and vals[i + 1] is not None:
                vals[i] = vals[i + 1]
        for i in range(n):  # forward
            if vals[i] is None:
                for j in range(i - 1, -1, -1):
                    if vals[j] is not None:
                        vals[i] = vals[j]
                        break
        return PriceSeries(self.first_hour, tuple(vals))


def _extract(attrs: dict, prefix: str) -> dict[int, float]:
    """Extract {hour: price} for attributes matching price_XXh."""
    out: dict[int, float] = {}
    for key, value in attrs.items():
        m = _PRICE_RE.match(key)
        if not m:
            continue
        is_next = key.startswith("price_next_day_")
        if prefix == "next_day" and not is_next:
            continue
        if prefix == "today" and is_next:
            continue
        try:
            out[int(m.group(1))] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def build_price_series(
    attributes: dict,
    now: datetime,
    horizon_hours: int,
) -> PriceSeries:
    """Build the price series covering [floor(now), +horizon_hours).

    Sources, in order: ``price_XXh`` for today, ``price_next_day_XXh``
    for tomorrow. Hours beyond available data stay ``None``.
    """
    today = _extract(attributes, "today")
    next_day = _extract(attributes, "next_day")

    first_hour = now.replace(minute=0, second=0, microsecond=0)
    midnight = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    prices: list[float | None] = []
    for i in range(horizon_hours):
        hour = first_hour + timedelta(hours=i)
        day = (hour - midnight).days
        h = hour.hour
        if day == 0:
            prices.append(today.get(h))
        elif day == 1:
            prices.append(next_day.get(h))
        else:
            prices.append(None)
    return PriceSeries(first_hour, tuple(prices))


def series_from_points(
    points: dict[datetime, float],
    first_hour: datetime,
    horizon_hours: int,
) -> tuple[float | None, ...]:
    """Align a {timestamp: value} map to an hourly series.

    Point timestamps may be in any tz; they are converted to the tz of
    ``first_hour`` and floored to the hour. Missing hours stay ``None``.
    """
    keyed: dict[datetime, float] = {}
    for ts, value in points.items():
        if ts.tzinfo is None:
            # Naive point: adopt the series tz (None stays naive).
            local = ts.replace(tzinfo=first_hour.tzinfo)
        else:
            local = ts.astimezone(first_hour.tzinfo)
        keyed[local.replace(minute=0, second=0, microsecond=0)] = value
    return tuple(
        keyed.get(first_hour + timedelta(hours=i))
        for i in range(horizon_hours)
    )
