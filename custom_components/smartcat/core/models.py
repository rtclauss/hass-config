"""Data models shared by the Smart Cat core."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Visit:
    """One litter box visit.

    `timestamp` is the anchor of the visit: the weigh-in time when the robot
    recorded a weight, otherwise the time the cat was first detected. It is
    always timezone aware (UTC).
    """

    robot_serial: str
    timestamp: datetime
    weight_lbs: float | None = None
    duration_s: float | None = None
    source: str = ""
    whisker_pet_id: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def key(self) -> str:
        """Return the stable de-duplication key for this visit."""
        return f"{self.robot_serial}:{int(self.timestamp.timestamp())}"


@dataclass(slots=True)
class Cat:
    """A cat profile known to Smart Cat."""

    cat_id: str
    name: str
    seed_lbs: float | None = None
    whisker_pet_id: str | None = None
    # Visits before this time are never attributed to this cat, so adding a
    # second cat later does not rewrite the first cat's history.
    active_from: datetime | None = None


@dataclass(slots=True)
class Assignment:
    """The result of identifying which cat made a visit."""

    cat_id: str | None
    confidence: float
    # "matched" (inside the cat's core band), "tail" (plausible partial
    # weigh-in), "pet_id" (robot supplied the pet), "assumed" (no weight, single
    # cat), "unknown" (no plausible cat).
    method: str
    # The weigh-in is a full reading of this cat: inside its symmetric core
    # band on that robot. Identity and weight quality are separate: a partial
    # weigh-in (or a pet-id visit with an odd weight) can be the right cat but
    # must not feed weight summaries, trends or alerts.
    weight_trusted: bool = False


@dataclass(slots=True)
class LevelReading:
    """A waste drawer / litter level sample for one robot."""

    robot_serial: str
    timestamp: datetime
    waste_pct: float | None
    litter_pct: float | None
    cycle_count: int | None


@dataclass(slots=True)
class NewCatCandidate:
    """A tight group of weights that matches no known cat."""

    median_lbs: float
    spread_lbs: float
    count: int
    days: int
    first_seen: datetime
    last_seen: datetime


@dataclass(slots=True)
class Anomaly:
    """A pattern change worth a human's attention."""

    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
