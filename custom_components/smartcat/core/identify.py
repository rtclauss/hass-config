"""Work out which cat made each visit, learning weights as it goes.

Weigh-ins are noisy in a specific way. When a cat keeps a paw on the step, the
robot records a partial weight that is too low. Individual robots also read
differently: in practice one unit can read about 2 lb heavier than another for
the same cat. The model handles both:

* each cat keeps a rolling window of trusted weights, globally and per robot,
  and its center is the median with a MAD-based spread, so partial weigh-ins
  do not drag it down;
* the low side of the band is wider than the high side, so partial weigh-ins
  are still attributed ("tail") but never learned from;
* weigh-ins that fit no cat go into a pool, and a tight, persistent group in
  that pool is reported as a likely new cat.

Identification is a deterministic replay over the whole history. It is cheap
(thousands of visits take milliseconds), and adding or removing a cat simply
re-attributes everything after that cat's `active_from`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from statistics import median

from .models import Assignment, Cat, NewCatCandidate, Visit

WINDOW = 60
MIN_SAMPLES = 5
MIN_SPREAD = 0.35
DEFAULT_SPREAD = 1.0
BOOTSTRAP_SPREAD = 1.25
CORE_Z = 2.5
HIGH_TAIL_Z = 3.5
HIGH_TAIL_MIN_LBS = 2.5
LOW_TAIL_FACTOR = 1.6
LOW_TAIL_MIN_LBS = 3.0
LOW_TAIL_SPREADS = 4.5
MIN_PLAUSIBLE_LBS = 1.0
LEARN_CONFIDENCE = 0.8
ASSUMED_CONFIDENCE = 0.6
SOLE_OUTLIER_CONFIDENCE = 0.3

CANDIDATE_LOOKBACK = timedelta(days=21)
CANDIDATE_RADIUS = 0.6
CANDIDATE_MIN_COUNT = 8
CANDIDATE_MIN_DAYS = 4
CANDIDATE_MIN_SEPARATION = 1.5
CANDIDATE_RUN_GAP = timedelta(days=2)
EMERGENCE_PRIOR = timedelta(days=14)
EMERGENCE_FACTOR = 3.0


def robust_spread(values: list[float]) -> float:
    """Return 1.4826 * MAD, a robust standard deviation estimate."""
    if len(values) < 2:
        return 0.0
    mid = median(values)
    return 1.4826 * median(abs(v - mid) for v in values)


@dataclass
class CatModel:
    """Learned weight profile for one cat."""

    cat: Cat
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    by_robot: dict[str, deque[float]] = field(default_factory=dict)

    def center(self, robot: str | None = None) -> float | None:
        """Return the cat's expected weight, robot-specific when known."""
        if robot and len(window := self.by_robot.get(robot, ())) >= MIN_SAMPLES:
            return median(window)
        if len(self.samples) >= MIN_SAMPLES:
            return median(self.samples)
        if self.cat.seed_lbs:
            return self.cat.seed_lbs
        return median(self.samples) if self.samples else None

    def spread(self, robot: str | None = None) -> float:
        """Return the cat's weight spread, robot-specific when known."""
        if robot and len(window := self.by_robot.get(robot, ())) >= MIN_SAMPLES * 2:
            return max(robust_spread(list(window)), MIN_SPREAD)
        if len(self.samples) >= MIN_SAMPLES * 2:
            return max(robust_spread(list(self.samples)), MIN_SPREAD)
        return DEFAULT_SPREAD

    def robot_established(self, robot: str) -> bool:
        """Return True once this robot has its own calibration for the cat."""
        return len(self.by_robot.get(robot, ())) >= MIN_SAMPLES

    def learn(self, robot: str, weight: float) -> None:
        """Add a trusted weigh-in."""
        self.samples.append(weight)
        self.by_robot.setdefault(robot, deque(maxlen=WINDOW)).append(weight)

    def centers(self) -> list[float]:
        """Return every center this cat is known by (global and per robot)."""
        values = [c for c in [self.center()] if c is not None]
        values += [
            median(w) for w in self.by_robot.values() if len(w) >= MIN_SAMPLES
        ]
        return values


@dataclass(slots=True)
class _Score:
    model: CatModel
    z: float
    band: str  # core | tail | out
    raw_z: float = 0.0


class Identifier:
    """Replay visits in time order, assigning cats and learning weights."""

    def __init__(self, cats: Iterable[Cat]) -> None:
        """Initialise with the known cat profiles."""
        self.models: dict[str, CatModel] = {c.cat_id: CatModel(c) for c in cats}
        # (time, weight, hard) for weigh-ins no cat explains well. `hard` means
        # outside every cat's band, not just in a cat's partial weigh-in tail.
        self.unmatched: list[tuple[datetime, float, bool]] = []
        self.first_visit: datetime | None = None

    def _eligible(self, when: datetime) -> list[CatModel]:
        return [
            m
            for m in self.models.values()
            if m.cat.active_from is None or m.cat.active_from <= when
        ]

    @staticmethod
    def _score(model: CatModel, robot: str, weight: float, sole: bool) -> _Score:
        center = model.center(robot)
        if center is None:
            # A cat with no seed and no samples accepts its first weigh-in.
            return _Score(model, 0.0, "core" if sole else "out")
        spread = model.spread(robot)
        if sole and not model.robot_established(robot):
            # Let a new robot calibrate against the only cat even if it reads
            # high or low compared with the other robot.
            spread = max(spread, BOOTSTRAP_SPREAD)
        delta = weight - center
        raw_z = delta / spread
        z = raw_z if delta >= 0 else delta / (spread * LOW_TAIL_FACTOR)
        if abs(z) <= CORE_Z:
            band = "core"
        elif delta > 0 and delta <= max(HIGH_TAIL_Z * spread, HIGH_TAIL_MIN_LBS):
            band = "tail"
        elif delta < 0 and -delta <= max(LOW_TAIL_MIN_LBS, LOW_TAIL_SPREADS * spread):
            band = "tail"
        else:
            band = "out"
        return _Score(model, z, band, raw_z)

    def assign(self, visit: Visit) -> Assignment:
        """Assign one visit (call in chronological order)."""
        if self.first_visit is None:
            self.first_visit = visit.timestamp
        eligible = self._eligible(visit.timestamp)
        weight = visit.weight_lbs
        if weight is not None and weight < MIN_PLAUSIBLE_LBS:
            weight = None

        if visit.whisker_pet_id:
            for model in eligible:
                if model.cat.whisker_pet_id == visit.whisker_pet_id:
                    if weight is not None:
                        score = self._score(model, visit.robot_serial, weight, True)
                        if score.band == "core" and abs(score.raw_z) <= CORE_Z:
                            model.learn(visit.robot_serial, weight)
                    return Assignment(model.cat.cat_id, 1.0, "pet_id")

        if weight is None:
            if len(eligible) == 1:
                return Assignment(eligible[0].cat.cat_id, ASSUMED_CONFIDENCE, "assumed")
            return Assignment(None, 0.0, "unknown")

        sole = len(eligible) == 1
        scores = [self._score(m, visit.robot_serial, weight, sole) for m in eligible]
        plausible = [s for s in scores if s.band != "out"]
        if not plausible:
            self.unmatched.append((visit.timestamp, weight, True))
            # With one cat there is nobody else a light reading could be: a
            # very partial weigh-in is still that cat's visit.
            if sole and (center := eligible[0].center(visit.robot_serial)) is not None:
                if weight < center:
                    return Assignment(eligible[0].cat.cat_id, SOLE_OUTLIER_CONFIDENCE, "tail")
            return Assignment(None, 0.0, "unknown")

        likelihood = {id(s): math.exp(-0.5 * s.z * s.z) for s in plausible}
        total = sum(likelihood.values())
        best = max(plausible, key=lambda s: likelihood[id(s)])
        share = likelihood[id(best)] / total if total > 1e-300 else 1.0 / len(plausible)
        if best.band == "core":
            confidence = round(share, 3)
            # Learn only from symmetric core weigh-ins: the widened low side
            # exists to attribute partial weigh-ins, not to learn from them.
            if confidence >= LEARN_CONFIDENCE and abs(best.raw_z) <= CORE_Z:
                best.model.learn(visit.robot_serial, weight)
            return Assignment(best.model.cat.cat_id, confidence, "matched")

        # A tail match is a plausible partial weigh-in, but it is also what a
        # new cat of similar size looks like at first.
        self.unmatched.append((visit.timestamp, weight, False))
        return Assignment(best.model.cat.cat_id, round(0.5 * share, 3), "tail")

    def new_cat_candidate(self, now: datetime) -> NewCatCandidate | None:
        """Return a tight, persistent, recently emerged group of weights.

        Two kinds of tight clusters exist in the pool: a new cat, and an
        existing cat's habit of weighing in partially (paw on the step). The
        second sits inside a cat's tail band and has been there all along, so
        a cluster only qualifies if it is mostly outside every cat's band, or
        if its rate in the latest run is well above its earlier rate.
        """
        recent = [u for u in self.unmatched if now - u[0] <= CANDIDATE_LOOKBACK]
        if len(recent) < CANDIDATE_MIN_COUNT:
            return None
        best: list[tuple[datetime, float, bool]] = []
        for _, anchor, _ in recent:
            group = [u for u in recent if abs(u[1] - anchor) <= CANDIDATE_RADIUS]
            if len(group) > len(best):
                best = group
        if len(best) < CANDIDATE_MIN_COUNT:
            return None
        mid = median(u[1] for u in best)
        lo, hi = mid - CANDIDATE_RADIUS, mid + CANDIDATE_RADIUS
        for model in self.models.values():
            if any(abs(mid - c) < CANDIDATE_MIN_SEPARATION for c in model.centers()):
                return None

        # The new cat's arrival is the start of the latest contiguous run;
        # older matches are scattered partial weigh-ins of the existing cats.
        times = sorted(u[0] for u in best)
        first = times[-1]
        for earlier in reversed(times[:-1]):
            if first - earlier > CANDIDATE_RUN_GAP:
                break
            first = earlier
        run = [u for u in best if u[0] >= first]
        days = {u[0].date() for u in run}
        if len(run) < CANDIDATE_MIN_COUNT or len(days) < CANDIDATE_MIN_DAYS:
            return None

        hard = sum(1 for u in run if u[2]) / len(run)
        if hard < 0.5 and not self._emerged(run, first, lo, hi):
            return None

        weights = [u[1] for u in run]
        return NewCatCandidate(
            median_lbs=round(median(weights), 2),
            spread_lbs=round(robust_spread(weights), 2),
            count=len(run),
            days=len(days),
            first_seen=first,
            last_seen=times[-1],
        )

    def _emerged(
        self, run: list[tuple[datetime, float, bool]], first: datetime, lo: float, hi: float
    ) -> bool:
        """Return True if this weight band is new compared with earlier history."""
        if self.first_visit is None or first - self.first_visit < EMERGENCE_PRIOR:
            return False  # not enough earlier history to tell
        run_days = max((run[-1][0] - first).total_seconds() / 86400, 1.0)
        prior_days = (first - self.first_visit).total_seconds() / 86400
        prior = sum(1 for t, w, _ in self.unmatched if t < first and lo <= w <= hi)
        return len(run) / run_days >= EMERGENCE_FACTOR * max(prior / prior_days, 1 / prior_days)


def identify_all(
    cats: Iterable[Cat], visits: Iterable[Visit]
) -> tuple[dict[str, Assignment], Identifier]:
    """Assign every visit to a cat. Returns assignments by visit key."""
    identifier = Identifier(cats)
    assignments: dict[str, Assignment] = {}
    for visit in sorted(visits, key=lambda v: v.timestamp):
        assignments[visit.key] = identifier.assign(visit)
    return assignments, identifier
