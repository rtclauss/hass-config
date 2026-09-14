from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


STATE_FILENAME = "last_good_reading.json"


@dataclass(frozen=True)
class LastGoodReading:
    value: float
    timestamp: str  # ISO 8601, UTC
    history: tuple[float, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    value: float | None
    reason: str
    stuck: bool = False


def load_last_good(state_dir: Path) -> LastGoodReading | None:
    path = state_dir / STATE_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "value" not in data or "timestamp" not in data:
        return None
    return LastGoodReading(
        value=float(data["value"]),
        timestamp=str(data["timestamp"]),
        history=tuple(float(v) for v in data.get("history", [])),
    )


def save_last_good(state_dir: Path, reading: LastGoodReading) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / STATE_FILENAME
    payload = {
        "value": reading.value,
        "timestamp": reading.timestamp,
        "history": list(reading.history),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def validate_reading(
    raw_digits: str,
    *,
    digit_count: int,
    max_gallons_per_interval: float,
    last_good: LastGoodReading | None,
    now: datetime | None = None,
    history_limit: int = 20,
    decimal_places: int = 0,
) -> ValidationResult:
    """Gate a freshly-OCR'd reading before it is ever published to HA.

    Rejects anything that isn't a clean numeric read of the expected digit
    count, that runs backward, or that jumps further than physically
    plausible for one polling interval. A bad read must never reach HA's
    long-term (total_increasing) statistics.

    decimal_places treats the LAST N OCR'd digits as fractional - this
    meter's display has a fixed decimal point before its final digit (e.g.
    the raw read "02138978" is actually 213897.8 gallons), confirmed against
    real captures rather than assumed. max_gallons_per_interval is compared
    in these same real-gallons units regardless of decimal_places, so its
    meaning (max plausible flow per polling interval) doesn't shift when
    this changes.
    """
    now = now or datetime.now(timezone.utc)

    if not raw_digits.isdigit():
        return ValidationResult(False, None, f"non-numeric read: {raw_digits!r}")

    if len(raw_digits) != digit_count:
        return ValidationResult(
            False, None, f"expected {digit_count} digits, got {len(raw_digits)}: {raw_digits!r}"
        )

    value = int(raw_digits) / (10**decimal_places)

    if last_good is None:
        return ValidationResult(True, value, "ok (first reading)", stuck=False)

    if value < last_good.value:
        return ValidationResult(
            False, None, f"value decreased: {value} < {last_good.value}"
        )

    delta = value - last_good.value
    if delta > max_gallons_per_interval:
        return ValidationResult(
            False,
            None,
            f"implausible jump: +{delta} exceeds max {max_gallons_per_interval}",
        )

    history = (*last_good.history, value)[-history_limit:]
    stuck = len(history) >= history_limit and len(set(history)) == 1
    return ValidationResult(True, value, "ok", stuck=stuck)


def next_last_good(value: float, previous: LastGoodReading | None, *, history_limit: int, now: datetime | None = None) -> LastGoodReading:
    now = now or datetime.now(timezone.utc)
    history = (*(previous.history if previous else ()), value)[-history_limit:]
    return LastGoodReading(value=value, timestamp=now.isoformat(), history=history)
