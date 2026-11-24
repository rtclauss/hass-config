"""Turn raw Whisker activity feeds into `Visit` records.

Litter-Robot 4 (GraphQL activity feed, via pylitterbot `get_activity_history`)
reports discrete events: cat detected, pet weight recorded, clean cycle started.
A visit is reconstructed from them:

    detect ... weight ... [cat leaves] ... <wait time> ... clean cycle

The robot starts its clean cycle exactly `wait` minutes after the last time the
cat sensor cleared, so `cycle_start - wait` estimates when the cat left.

Litter-Robot 5 (REST `/activities`) reports `PET_VISIT` records that already
carry a pet id, weight and duration; we only normalise field names and units.
The exact LR5 field names are not documented, so parsing is deliberately
tolerant and the raw record is kept alongside the visit for later reparsing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
from typing import Any

from .models import Visit

# LR4 event kinds.
DETECT = "detect"
WEIGHT = "weight"
CYCLE = "cycle"

# A visit cannot plausibly start more than this long before its weigh-in.
MAX_PRE_WEIGH = timedelta(minutes=15)
# Ignore a clean cycle this long after the wait period: something else (a
# manual cycle, a pause, an outage) happened in between.
MAX_CYCLE_SLACK = timedelta(minutes=60)
MAX_DURATION_S = 30 * 60

_WEIGHT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*lbs?", re.IGNORECASE)

# LitterBoxStatus member names (pylitterbot) mapped to event kinds. Matching by
# name keeps this module free of a pylitterbot import.
_STATUS_KINDS = {
    "CAT_DETECTED": DETECT,
    "CAT_SENSOR_INTERRUPTED": DETECT,
    "CLEAN_CYCLE": CYCLE,
}


@dataclass(slots=True, frozen=True)
class LR4Event:
    """A normalised LR4 activity event."""

    timestamp: datetime
    kind: str
    weight_lbs: float | None = None


def _as_utc(value: datetime | date) -> datetime:
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def lr4_event(timestamp: datetime | date, action: Any) -> LR4Event | None:
    """Normalise one pylitterbot `Activity` (timestamp, action) for an LR4."""
    ts = _as_utc(timestamp)
    name = getattr(action, "name", None)
    if name is not None:
        kind = _STATUS_KINDS.get(name)
        return LR4Event(ts, kind) if kind else None
    text = str(action)
    if text.startswith("Pet Weight Recorded"):
        match = _WEIGHT_RE.search(text)
        if not match:
            return None
        weight = float(match.group(1))
        return LR4Event(ts, WEIGHT, weight) if weight > 0 else None
    # Raw values that pylitterbot passes through unmapped.
    if text in ("robotStatusCatDetect", "robotCycleStateCatDetect"):
        return LR4Event(ts, DETECT)
    if text == "robotCycleStatusDump":
        return LR4Event(ts, CYCLE)
    return None


_RAW_DETECT = {"robotStatusCatDetect", "robotCycleStateCatDetect"}
_RAW_CYCLE = {"robotCycleStatusDump"}


def lr4_raw_event(row: Mapping[str, Any]) -> LR4Event | None:
    """Normalise one raw `getLitterRobot4Activity` GraphQL row."""
    ts = _parse_ts(row.get("timestamp"))
    if ts is None:
        return None
    value = row.get("value")
    if value in _RAW_DETECT:
        return LR4Event(ts, DETECT)
    if value in _RAW_CYCLE:
        return LR4Event(ts, CYCLE)
    if value == "catWeight":
        try:
            weight = float(row.get("actionValue"))
        except (TypeError, ValueError):
            return None
        return LR4Event(ts, WEIGHT, weight) if weight > 0 else None
    return None


def lr4_visits(
    serial: str,
    events: Iterable[LR4Event],
    wait_minutes: float,
    now: datetime | None = None,
) -> list[Visit]:
    """Reconstruct LR4 visits from normalised events.

    Events are split into segments by clean cycles. Inside a segment every
    weigh-in is one visit; a closed segment with detections but no weigh-in
    becomes one visit without a weight. Only the last visit of a closed segment
    gets a duration, since only its exit time can be inferred from the cycle
    start.

    The trailing segment is still open (no clean cycle yet). Its weigh-ins are
    returned, keyed by their own timestamps, so a later fetch updates them in
    place. A detection there without a weigh-in is not returned yet: the
    weight may still arrive, and that visit would be keyed by the weigh-in, not
    the detection, so returning it now would count one trip twice. Callers
    re-fetch from `lr4_open_since` so the segment is seen again once it closes.
    """
    wait = timedelta(minutes=wait_minutes)
    ordered = sorted(events, key=lambda e: (e.timestamp, e.kind != DETECT))
    visits: list[Visit] = []
    segment: list[LR4Event] = []

    def close(cycle_at: datetime | None) -> None:
        if not segment:
            return
        weights = [e for e in segment if e.kind == WEIGHT]
        detects = [e for e in segment if e.kind == DETECT]
        exit_at: datetime | None = None
        if cycle_at is not None:
            candidate = cycle_at - wait
            last_event = segment[-1].timestamp
            if candidate >= last_event - timedelta(seconds=5) and (
                cycle_at - last_event <= wait + MAX_CYCLE_SLACK
            ):
                exit_at = max(candidate, last_event)

        if not weights:
            if detects and cycle_at is not None:
                start = detects[0].timestamp
                visits.append(
                    Visit(
                        serial,
                        start,
                        None,
                        _duration(start, exit_at),
                        "lr4",
                    )
                )
            return

        previous_boundary: datetime | None = None
        for index, weigh in enumerate(weights):
            start = weigh.timestamp
            for det in detects:
                if det.timestamp > weigh.timestamp:
                    break
                if previous_boundary is not None and det.timestamp <= previous_boundary:
                    continue
                if weigh.timestamp - det.timestamp <= MAX_PRE_WEIGH:
                    start = det.timestamp
                    break
            is_last = index == len(weights) - 1
            visits.append(
                Visit(
                    serial,
                    weigh.timestamp,
                    weigh.weight_lbs,
                    _duration(start, exit_at) if is_last else None,
                    "lr4",
                    raw={"start": start.isoformat()},
                )
            )
            previous_boundary = weigh.timestamp

    for event in ordered:
        if event.kind == CYCLE:
            close(event.timestamp)
            segment = []
        else:
            segment.append(event)
    close(None)
    return visits


def lr4_open_since(events: Iterable[LR4Event]) -> datetime | None:
    """Return when the trailing, not yet cycled segment began, if there is one."""
    open_since: datetime | None = None
    for event in sorted(events, key=lambda e: (e.timestamp, e.kind != DETECT)):
        if event.kind == CYCLE:
            open_since = None
        elif open_since is None:
            open_since = event.timestamp
    return open_since


def _duration(start: datetime, exit_at: datetime | None) -> float | None:
    if exit_at is None:
        return None
    seconds = (exit_at - start).total_seconds()
    if seconds < 0:
        return None
    return float(min(seconds, MAX_DURATION_S))


# --- Litter-Robot 5 ------------------------------------------------------------

_LR5_TS_KEYS = ("timestamp", "createdAt", "eventTime", "time")
_LR5_DURATION_KEYS = ("duration", "durationSeconds", "visitDuration", "durationInSeconds")
_LR5_WEIGHT_KEYS = ("weight", "petWeight", "weightLbs", "catWeight", "weightSensor")
_LR5_PET_KEYS = ("petId", "pet_id")
_LR5_PET_LIST_KEYS = ("petIds", "pets")


def _first(record: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if (value := record.get(key)) not in (None, ""):
            return value
    data = record.get("data") or record.get("details")
    if isinstance(data, Mapping):
        for key in keys:
            if (value := data.get(key)) not in (None, ""):
                return value
    return None


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, UTC)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if " " in text and "T" not in text:
            text = text.replace(" ", "T", 1)
        try:
            return _as_utc(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def _lr5_weight(value: Any) -> float | None:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return None
    if weight <= 0:
        return None
    # LR5 reports the live weight sensor as pounds * 100.
    if weight > 100:
        weight /= 100
    return round(weight, 2)


def _lr5_duration(value: Any) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if duration < 0:
        return None
    if duration > MAX_DURATION_S * 10:  # milliseconds
        duration /= 1000
    return float(min(duration, MAX_DURATION_S))


def _lr5_pet(record: Mapping[str, Any]) -> str | None:
    if (pet := _first(record, _LR5_PET_KEYS)) is not None:
        return str(pet)
    pets = _first(record, _LR5_PET_LIST_KEYS)
    if isinstance(pets, list) and len(pets) == 1:
        only = pets[0]
        if isinstance(only, Mapping):
            only = only.get("petId") or only.get("id")
        return str(only) if only else None
    return None


def lr5_visits(serial: str, records: Iterable[Mapping[str, Any]]) -> list[Visit]:
    """Convert LR5 `/activities` records into visits.

    Uses `PET_VISIT` records when the feed has any; otherwise falls back to
    `CAT_DETECT` records (visits without weight or duration).
    """
    records = [r for r in records if isinstance(r, Mapping)]
    pet_visits = [r for r in records if str(r.get("type", "")).upper() == "PET_VISIT"]
    use = pet_visits or [
        r for r in records if str(r.get("type", "")).upper() == "CAT_DETECT"
    ]
    visits: list[Visit] = []
    for record in use:
        ts = _parse_ts(_first(record, _LR5_TS_KEYS))
        if ts is None:
            continue
        visits.append(
            Visit(
                serial,
                ts,
                _lr5_weight(_first(record, _LR5_WEIGHT_KEYS)),
                _lr5_duration(_first(record, _LR5_DURATION_KEYS)),
                "lr5",
                _lr5_pet(record),
                raw=dict(record),
            )
        )
    return visits


def lr5_record_time(record: Mapping[str, Any]) -> datetime | None:
    """Return the timestamp of an LR5 activity record, if parseable."""
    return _parse_ts(_first(record, _LR5_TS_KEYS))
