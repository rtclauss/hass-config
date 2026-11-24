"""Publish per-cat history as Home Assistant long-term statistics.

Long-term statistics are not purged by the recorder, so backfilled history
(years of it) shows up in statistics-graph cards and the energy-style history
views next to live data.

Statistic ids (external, `smartcat:` prefix):
  smartcat:<cat>_visits          hourly visit count (sum, use "change")
  smartcat:<cat>_weight          hourly mean / min / max weight (lb)
  smartcat:<cat>_visit_duration  hourly mean / min / max visit duration (s)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .core.models import Assignment, Cat, Visit

KINDS = ("visits", "weight", "visit_duration")


def statistic_id(cat_id: str, kind: str) -> str:
    """Return the external statistic id for a cat metric."""
    return f"{DOMAIN}:{cat_id}_{kind}"


def _hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def build_cat_statistics(
    visits: Sequence[Visit],
    assignments: dict[str, Assignment],
    cat_id: str,
    since: datetime | None,
) -> dict[str, list[StatisticData]]:
    """Build hourly rows for one cat, from `since` (hour) onward."""
    counts: dict[datetime, int] = defaultdict(int)
    weights: dict[datetime, list[float]] = defaultdict(list)
    durations: dict[datetime, list[float]] = defaultdict(list)
    for visit in visits:
        assignment = assignments.get(visit.key)
        if assignment is None or assignment.cat_id != cat_id:
            continue
        hour = _hour(visit.timestamp)
        counts[hour] += 1
        if visit.weight_lbs is not None and assignment.weight_trusted:
            weights[hour].append(visit.weight_lbs)
        if visit.duration_s is not None:
            durations[hour].append(visit.duration_s)

    start = _hour(since) if since else None
    total = 0
    visit_rows: list[StatisticData] = []
    for hour in sorted(counts):
        total += counts[hour]
        if start is None or hour >= start:
            visit_rows.append(StatisticData(start=hour, state=counts[hour], sum=total))

    def mean_rows(values: dict[datetime, list[float]]) -> list[StatisticData]:
        return [
            StatisticData(
                start=hour,
                mean=round(sum(v) / len(v), 3),
                min=min(v),
                max=max(v),
            )
            for hour, v in sorted(values.items())
            if start is None or hour >= start
        ]

    return {
        "visits": visit_rows,
        "weight": mean_rows(weights),
        "visit_duration": mean_rows(durations),
    }


def _metadata(cat: Cat, kind: str) -> StatisticMetaData:
    if kind == "visits":
        return StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{cat.name} visits",
            source=DOMAIN,
            statistic_id=statistic_id(cat.cat_id, kind),
            unit_class=None,
            unit_of_measurement="visits",
        )
    if kind == "weight":
        return StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=f"{cat.name} weight",
            source=DOMAIN,
            statistic_id=statistic_id(cat.cat_id, kind),
            unit_class="mass",
            unit_of_measurement=UnitOfMass.POUNDS,
        )
    return StatisticMetaData(
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name=f"{cat.name} visit duration",
        source=DOMAIN,
        statistic_id=statistic_id(cat.cat_id, kind),
        unit_class="duration",
        unit_of_measurement=UnitOfTime.SECONDS,
    )


@callback
def async_clear_cat_statistics(hass: HomeAssistant, cat_id: str) -> None:
    """Delete every statistic of one cat (rows and metadata)."""
    get_instance(hass).async_clear_statistics([statistic_id(cat_id, kind) for kind in KINDS])


@callback
def async_publish_cat_statistics(
    hass: HomeAssistant,
    cat: Cat,
    visits: Sequence[Visit],
    assignments: dict[str, Assignment],
    since: datetime | None,
    *,
    rebuild: bool = False,
) -> int:
    """Queue statistics rows for one cat. Returns the number of rows queued.

    Importing only adds or updates hours, so an hour that lost all its visits
    (a visit moved to another cat) would keep its old row. `rebuild` clears
    the cat's statistics first and re-imports all of them; the recorder runs
    both tasks in order.
    """
    if rebuild:
        async_clear_cat_statistics(hass, cat.cat_id)
        since = None
    rows = build_cat_statistics(visits, assignments, cat.cat_id, since)
    queued = 0
    for kind, data in rows.items():
        if data:
            async_add_external_statistics(hass, _metadata(cat, kind), data)
            queued += len(data)
    return queued
