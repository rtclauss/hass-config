"""Forecast when the waste drawer fills and when litter needs topping up.

Both levels move with clean cycles, not with time. Each cycle drops one load
of waste into the drawer and carries a little litter away with it. So:

    rate per cycle  = robust slope of level vs. cumulative cycle count,
                      fitted over the current fill period
    cycles per day  = recent cycle rate for the robot
    ETA             = now + (threshold - level) / (rate per cycle * cycles per day)

A fill period ends when the drawer is emptied (waste drops sharply) or litter
is added (litter jumps up). Early in a period, with too few points to fit, the
median slope from earlier periods is used instead. When cycle counts are not
available, the slope is fitted against time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .analytics import theil_sen
from .models import LevelReading

WASTE_RESET_DROP = 15.0
LITTER_RESET_JUMP = 10.0
MIN_POINTS = 3
CYCLE_RATE_DAYS = 14
MIN_CYCLE_RATE_SPAN = timedelta(hours=12)
MAX_HORIZON_DAYS = 120


@dataclass(slots=True)
class LevelForecast:
    """Forecast for one level of one robot."""

    current: float | None
    threshold: float
    eta: datetime | None
    days_remaining: float | None
    rate_per_cycle: float | None
    rate_per_day: float | None
    cycles_per_day: float | None
    period_start: datetime | None
    points: int
    method: str  # current | cycles | prior_cycles | time | reached | unknown


def _periods(
    readings: Sequence[tuple[datetime, float, int | None]], rising: bool, reset: float
) -> list[list[tuple[datetime, float, int | None]]]:
    """Split readings into fill periods at resets."""
    periods: list[list[tuple[datetime, float, int | None]]] = []
    current: list[tuple[datetime, float, int | None]] = []
    for reading in readings:
        if current:
            delta = reading[1] - current[-1][1]
            if (rising and delta <= -reset) or (not rising and delta >= reset):
                periods.append(current)
                current = []
        current.append(reading)
    if current:
        periods.append(current)
    return periods


def _cumulative_cycles(period: Sequence[tuple[datetime, float, int | None]]) -> list[float] | None:
    """Return a monotonic cycle axis (sums positive deltas; counters may reset)."""
    if any(r[2] is None for r in period):
        return None
    axis = [0.0]
    for prev, cur in zip(period, period[1:]):
        axis.append(axis[-1] + max(0, cur[2] - prev[2]))  # type: ignore[operator]
    return axis


def _slope_vs_cycles(period: Sequence[tuple[datetime, float, int | None]]) -> tuple[float | None, int]:
    axis = _cumulative_cycles(period)
    if axis is None or axis[-1] <= 0:
        return None, 0
    points = list(zip(axis, (r[1] for r in period)))
    distinct = {x for x, _ in points}
    if len(distinct) < MIN_POINTS:
        return None, len(distinct)
    return theil_sen(points), len(distinct)


def cycles_per_day(
    readings: Sequence[LevelReading], now: datetime, fallback: float | None = None
) -> float | None:
    """Return the robot's recent clean cycle rate."""
    start = now - timedelta(days=CYCLE_RATE_DAYS)
    recent = [r for r in readings if r.timestamp >= start and r.cycle_count is not None]
    if len(recent) >= 2:
        span = recent[-1].timestamp - recent[0].timestamp
        total = sum(
            max(0, b.cycle_count - a.cycle_count)  # type: ignore[operator]
            for a, b in zip(recent, recent[1:])
        )
        if span >= MIN_CYCLE_RATE_SPAN and total > 0:
            return round(total / (span.total_seconds() / 86400), 2)
    return fallback


def forecast_level(
    readings: Sequence[LevelReading],
    *,
    waste: bool,
    threshold: float,
    now: datetime,
    cycle_rate: float | None,
) -> LevelForecast:
    """Forecast when a level crosses its threshold.

    `waste=True` forecasts the drawer rising to `threshold`. `waste=False`
    forecasts the litter falling to `threshold`.
    """
    series = [
        (r.timestamp, r.waste_pct if waste else r.litter_pct, r.cycle_count)
        for r in sorted(readings, key=lambda r: r.timestamp)
    ]
    series = [(t, float(v), c) for t, v, c in series if v is not None]
    empty = LevelForecast(None, threshold, None, None, None, None, cycle_rate, None, 0, "unknown")
    if not series:
        return empty

    periods = _periods(series, rising=waste, reset=WASTE_RESET_DROP if waste else LITTER_RESET_JUMP)
    period = periods[-1]
    current = period[-1][1]
    result = LevelForecast(
        current, threshold, None, None, None, None, cycle_rate, period[0][0], len(period), "unknown"
    )

    reached = current >= threshold if waste else current <= threshold
    if reached:
        result.eta, result.days_remaining, result.method = now, 0.0, "reached"
        return result

    sign = 1.0 if waste else -1.0
    slope, _ = _slope_vs_cycles(period)
    method = "cycles"
    if slope is None or slope * sign <= 0:
        prior = [
            s
            for p in periods[:-1]
            if (s := _slope_vs_cycles(p)[0]) is not None and s * sign > 0
        ]
        slope, method = (median(prior), "prior_cycles") if prior else (None, "unknown")

    per_day: float | None = None
    if slope is not None and cycle_rate:
        result.rate_per_cycle = round(slope, 3)
        per_day = slope * cycle_rate
    else:
        # Fall back to level vs. time within the current period.
        points = [((t - period[0][0]).total_seconds() / 86400, v) for t, v, _ in period]
        if len({round(x, 3) for x, _ in points}) >= MIN_POINTS and points[-1][0] >= 1.0:
            per_day = theil_sen(points)
            method = "time"

    if per_day is None or per_day * sign <= 0:
        result.method = "unknown"
        return result

    days = (threshold - current) / per_day
    if days > MAX_HORIZON_DAYS:
        result.rate_per_day = round(per_day, 3)
        result.method = method
        return result
    result.rate_per_day = round(per_day, 3)
    result.days_remaining = round(days, 2)
    result.eta = now + timedelta(days=days)
    result.method = method
    return result
