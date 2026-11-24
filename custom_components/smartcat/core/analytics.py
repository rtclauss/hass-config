"""Per-cat insights: daily activity, time-of-day pattern, weight and anomalies.

This covers what the Whisker+ screens show (daily summary, time-of-visit
graph, duration and frequency tracking, outlier and trend detection) using only
the visit history. Thresholds lean toward few false alarms. The output is not a
diagnosis.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from statistics import mean, median, pstdev

from .models import Anomaly, Assignment, Visit

BASELINE_DAYS = 28
MIN_BASELINE_DAYS = 7
HISTOGRAM_DAYS = 30
DAILY_SERIES_DAYS = 14
WEIGHT_RECENT_DAYS = 7
WEIGHT_TREND_DAYS = 60
WEIGHT_COMPARE_DAYS = 30
WEIGHT_MIN_READINGS = 5
WEIGHT_CHANGE_PCT = 5.0
FREQ_HIGH_Z = 2.5
FREQ_HIGH_MIN_EXTRA = 3
FREQ_LOW_Z = 2.5
FREQ_LOW_MIN_DROP = 2
LONG_VISIT_FACTOR = 2.5
LONG_VISIT_MIN_S = 180
NO_VISIT_MIN_HOURS = 24.0
NO_VISIT_GAP_FACTOR = 2.0

STATUS_INSUFFICIENT = "insufficient_data"
STATUS_NORMAL = "normal"
# Ordered by severity; the first present becomes the headline status.
ANOMALY_ORDER = (
    "no_recent_visits",
    "frequency_high",
    "weight_loss",
    "long_visit",
    "frequency_low",
    "weight_gain",
)


@dataclass(slots=True)
class CatInsights:
    """Computed insights for one cat."""

    cat_id: str
    visits_today: int = 0
    visits_yesterday: int = 0
    baseline_mean: float | None = None
    baseline_std: float | None = None
    baseline_days: int = 0
    last_visit: Visit | None = None
    last_visit_confidence: float | None = None
    avg_duration_today_s: float | None = None
    avg_duration_7d_s: float | None = None
    median_duration_30d_s: float | None = None
    weight_lbs: float | None = None
    weight_trend_lbs_per_week: float | None = None
    weight_change_30d_pct: float | None = None
    hourly_histogram: list[int] = field(default_factory=lambda: [0] * 24)
    daily_counts: dict[str, int] = field(default_factory=dict)
    usual_gap_hours: float | None = None
    total_visits: int = 0
    first_visit: datetime | None = None
    anomalies: list[Anomaly] = field(default_factory=list)

    @property
    def status(self) -> str:
        """Return the headline status."""
        kinds = {a.kind for a in self.anomalies}
        for kind in ANOMALY_ORDER:
            if kind in kinds:
                return kind
        if self.baseline_days < MIN_BASELINE_DAYS:
            return STATUS_INSUFFICIENT
        return STATUS_NORMAL


def theil_sen(points: Sequence[tuple[float, float]]) -> float | None:
    """Return the Theil-Sen slope (median of pairwise slopes)."""
    slopes = [
        (y2 - y1) / (x2 - x1)
        for i, (x1, y1) in enumerate(points)
        for x2, y2 in points[i + 1 :]
        if x2 != x1
    ]
    return median(slopes) if slopes else None


def _local_date(ts: datetime, tz: tzinfo) -> date:
    return ts.astimezone(tz).date()


def _percentile(values: Sequence[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty")
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def cat_insights(
    cat_id: str,
    visits: Sequence[Visit],
    assignments: dict[str, Assignment],
    now: datetime,
    tz: tzinfo,
) -> CatInsights:
    """Compute insights for one cat from its visits (any order)."""
    visits = sorted(visits, key=lambda v: v.timestamp)
    out = CatInsights(cat_id)
    if not visits:
        return out

    today = _local_date(now, tz)
    yesterday = today - timedelta(days=1)
    out.total_visits = len(visits)
    out.first_visit = visits[0].timestamp
    out.last_visit = visits[-1]
    out.last_visit_confidence = assignments[visits[-1].key].confidence

    per_day: Counter[date] = Counter(_local_date(v.timestamp, tz) for v in visits)
    out.visits_today = per_day.get(today, 0)
    out.visits_yesterday = per_day.get(yesterday, 0)
    out.daily_counts = {
        (today - timedelta(days=i)).isoformat(): per_day.get(today - timedelta(days=i), 0)
        for i in range(DAILY_SERIES_DAYS - 1, -1, -1)
    }

    # Baseline: complete days before yesterday, from the first visit onward,
    # so yesterday can be compared against it too.
    first_day = _local_date(visits[0].timestamp, tz)
    baseline_dates = [
        d
        for i in range(2, BASELINE_DAYS + 2)
        if (d := today - timedelta(days=i)) >= first_day
    ]
    out.baseline_days = len(baseline_dates)
    if baseline_dates:
        counts = [per_day.get(d, 0) for d in baseline_dates]
        out.baseline_mean = round(mean(counts), 2)
        out.baseline_std = round(pstdev(counts), 2)

    hist_start = now - timedelta(days=HISTOGRAM_DAYS)
    for v in visits:
        if v.timestamp >= hist_start:
            out.hourly_histogram[v.timestamp.astimezone(tz).hour] += 1

    # Durations.
    def durations_since(start: datetime) -> list[float]:
        return [
            v.duration_s
            for v in visits
            if v.duration_s is not None and v.timestamp >= start
        ]

    today_start = datetime.combine(today, datetime.min.time(), tz)
    if d := durations_since(today_start):
        out.avg_duration_today_s = round(mean(d), 1)
    if d := durations_since(now - timedelta(days=7)):
        out.avg_duration_7d_s = round(mean(d), 1)
    if d := durations_since(now - timedelta(days=30)):
        out.median_duration_30d_s = round(median(d), 1)

    # Weight: only weigh-ins that matched the core band (no partial weigh-ins).
    trusted = [
        v
        for v in visits
        if v.weight_lbs is not None
        and assignments[v.key].method in ("matched", "pet_id")
        and assignments[v.key].confidence >= 0.5
    ]
    recent = [v.weight_lbs for v in trusted if v.timestamp >= now - timedelta(days=WEIGHT_RECENT_DAYS)]
    if len(recent) >= 3:
        out.weight_lbs = round(median(recent), 2)
    elif trusted:
        out.weight_lbs = round(median([v.weight_lbs for v in trusted[-WEIGHT_MIN_READINGS:]]), 2)

    daily_weight: dict[date, list[float]] = {}
    for v in trusted:
        if v.timestamp >= now - timedelta(days=WEIGHT_TREND_DAYS):
            daily_weight.setdefault(_local_date(v.timestamp, tz), []).append(v.weight_lbs)
    if len(daily_weight) >= 7:
        points = [((d - today).days, median(ws)) for d, ws in sorted(daily_weight.items())]
        if (slope := theil_sen(points)) is not None:
            out.weight_trend_lbs_per_week = round(slope * 7, 3)

    cut = now - timedelta(days=WEIGHT_COMPARE_DAYS)
    last30 = [v.weight_lbs for v in trusted if v.timestamp >= cut]
    prev30 = [
        v.weight_lbs
        for v in trusted
        if cut - timedelta(days=WEIGHT_COMPARE_DAYS) <= v.timestamp < cut
    ]
    if len(last30) >= WEIGHT_MIN_READINGS and len(prev30) >= WEIGHT_MIN_READINGS:
        before = median(prev30)
        out.weight_change_30d_pct = round((median(last30) - before) / before * 100, 2)

    # Usual gap between visits (90th percentile over 30 days).
    window = [v.timestamp for v in visits if v.timestamp >= now - timedelta(days=30)]
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(window, window[1:])]
    if len(gaps) >= 5:
        out.usual_gap_hours = round(_percentile(gaps, 0.9), 2)

    out.anomalies = _anomalies(out, visits, now)
    return out


def _anomalies(out: CatInsights, visits: Sequence[Visit], now: datetime) -> list[Anomaly]:
    found: list[Anomaly] = []
    enough = out.baseline_days >= MIN_BASELINE_DAYS and out.baseline_mean is not None

    if enough:
        mu, sd = out.baseline_mean, out.baseline_std or 0.0
        high_at = mu + max(FREQ_HIGH_Z * sd, FREQ_HIGH_MIN_EXTRA)
        for label, count in (("today", out.visits_today), ("yesterday", out.visits_yesterday)):
            if count >= high_at:
                found.append(
                    Anomaly(
                        "frequency_high",
                        f"{count} visits {label}, usually about {mu:.1f} a day.",
                        {"day": label, "count": count, "baseline": mu},
                    )
                )
                break
        low_at = mu - max(FREQ_LOW_Z * sd, FREQ_LOW_MIN_DROP)
        if mu >= FREQ_LOW_MIN_DROP and out.visits_yesterday <= low_at:
            found.append(
                Anomaly(
                    "frequency_low",
                    f"Only {out.visits_yesterday} visits yesterday, usually about {mu:.1f} a day.",
                    {"count": out.visits_yesterday, "baseline": mu},
                )
            )

        if out.last_visit is not None:
            hours = (now - out.last_visit.timestamp).total_seconds() / 3600
            limit = max(NO_VISIT_MIN_HOURS, NO_VISIT_GAP_FACTOR * (out.usual_gap_hours or 0))
            if hours >= limit:
                found.append(
                    Anomaly(
                        "no_recent_visits",
                        f"No visits in {hours:.0f} hours.",
                        {"hours": round(hours, 1), "limit_hours": round(limit, 1)},
                    )
                )

    if out.median_duration_30d_s:
        limit = max(LONG_VISIT_FACTOR * out.median_duration_30d_s, LONG_VISIT_MIN_S)
        long_ones = [
            v
            for v in visits
            if v.duration_s is not None
            and v.timestamp >= now - timedelta(hours=24)
            and v.duration_s >= limit
        ]
        if long_ones and out.total_visits >= 20:
            worst = max(long_ones, key=lambda v: v.duration_s or 0)
            found.append(
                Anomaly(
                    "long_visit",
                    f"A {worst.duration_s / 60:.1f} minute visit, usually about "
                    f"{out.median_duration_30d_s / 60:.1f} minutes.",
                    {
                        "duration_s": worst.duration_s,
                        "median_s": out.median_duration_30d_s,
                        "at": worst.timestamp.isoformat(),
                    },
                )
            )

    if (change := out.weight_change_30d_pct) is not None:
        if change <= -WEIGHT_CHANGE_PCT:
            found.append(
                Anomaly(
                    "weight_loss",
                    f"Weight down {abs(change):.1f}% over the last 30 days.",
                    {"change_pct": change},
                )
            )
        elif change >= WEIGHT_CHANGE_PCT:
            found.append(
                Anomaly(
                    "weight_gain",
                    f"Weight up {change:.1f}% over the last 30 days.",
                    {"change_pct": change},
                )
            )
    return found
