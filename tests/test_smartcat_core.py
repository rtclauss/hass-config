"""Smart Cat core: identification, analytics, forecasts and storage.

The core under custom_components/smartcat/core is plain Python, so these tests
run in the normal suite without Home Assistant. The integration tests that need
Home Assistant live in tests/smartcat_ha (see docs/smartcat.md).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
import random
import sys
import types
from zoneinfo import ZoneInfo

import pytest

# Importing custom_components.smartcat would run its __init__, which imports
# Home Assistant. Register the package without running it so only the
# HA-independent core is loaded.
_PACKAGE = "custom_components.smartcat"
if _PACKAGE not in sys.modules:
    _root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(_root))
    _module = types.ModuleType(_PACKAGE)
    _module.__path__ = [str(_root / "custom_components" / "smartcat")]
    sys.modules[_PACKAGE] = _module

from custom_components.smartcat.core.analytics import cat_insights
from custom_components.smartcat.core.forecast import cycles_per_day, forecast_level
from custom_components.smartcat.core.identify import identify_all
from custom_components.smartcat.core.models import Assignment, Cat, LevelReading, Visit
from custom_components.smartcat.core.parse import (
    lr4_event,
    lr4_open_since,
    lr4_raw_event,
    lr4_visits,
    lr5_visits,
)
from custom_components.smartcat.core.store import Store

TZ = ZoneInfo("America/Denver")  # synthetic; the real one is a secret


class Status(Enum):
    """Stand-in for pylitterbot.LitterBoxStatus (matched by member name)."""

    CAT_DETECTED = "CD"
    CAT_SENSOR_INTERRUPTED = "CSI"
    CLEAN_CYCLE = "CCP"
    CLEAN_CYCLE_COMPLETE = "CCC"


def t(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# --- parsing -----------------------------------------------------------------


def test_lr4_event_normalisation() -> None:
    ts = t("2026-11-21T12:20:00")
    assert lr4_event(ts, Status.CAT_DETECTED).kind == "detect"
    assert lr4_event(ts, Status.CLEAN_CYCLE).kind == "cycle"
    assert lr4_event(ts, Status.CLEAN_CYCLE_COMPLETE) is None
    weight = lr4_event(ts, "Pet Weight Recorded: 13.13 lbs")
    assert weight.kind == "weight" and weight.weight_lbs == 13.13
    assert lr4_event(ts, "Pet Weight Recorded: 0 lbs") is None
    assert lr4_event(ts, "Clean Cycles: 7") is None


def test_lr4_raw_rows() -> None:
    weight = lr4_raw_event({"timestamp": "2026-11-23 05:49:57.000", "value": "catWeight", "actionValue": "13.13"})
    assert weight.kind == "weight" and weight.weight_lbs == 13.13
    assert weight.timestamp == t("2026-11-23T05:49:57")
    assert lr4_raw_event({"timestamp": "2026-11-23T05:47:41Z", "value": "robotStatusCatDetect"}).kind == "detect"
    assert lr4_raw_event({"timestamp": "2026-11-23T06:09:03Z", "value": "robotCycleStatusDump"}).kind == "cycle"
    assert lr4_raw_event({"timestamp": "2026-11-23T06:09:03Z", "value": "odometerCleanCycles"}) is None
    assert lr4_raw_event({"timestamp": None, "value": "catWeight"}) is None


def test_lr4_visit_reconstruction_matches_observed_sequence() -> None:
    # Observed 2026-11-21 on the Main Level LR4 (7 min wait):
    # cd 12:19:52, weight 12:25:07, ccp 12:32:07.
    events = [
        lr4_event(t("2026-11-21T12:19:52"), Status.CAT_DETECTED),
        lr4_event(t("2026-11-21T12:25:07"), "Pet Weight Recorded: 6.49 lbs"),
        lr4_event(t("2026-11-21T12:32:07"), Status.CLEAN_CYCLE),
    ]
    (visit,) = lr4_visits("LR4X", events, wait_minutes=7)
    assert visit.timestamp == t("2026-11-21T12:25:07")
    assert visit.weight_lbs == 6.49
    # Left at 12:25:07 at the latest; cycle - wait = 12:25:07.
    assert visit.duration_s == pytest.approx(315)


def test_lr4_two_cats_in_one_wait_window() -> None:
    events = [
        lr4_event(t("2026-11-21T08:00:00"), Status.CAT_DETECTED),
        lr4_event(t("2026-11-21T08:01:00"), "Pet Weight Recorded: 11 lbs"),
        lr4_event(t("2026-11-21T08:04:00"), Status.CAT_DETECTED),
        lr4_event(t("2026-11-21T08:05:00"), "Pet Weight Recorded: 8 lbs"),
        lr4_event(t("2026-11-21T08:13:00"), Status.CLEAN_CYCLE),
    ]
    first, second = lr4_visits("LR4X", events, wait_minutes=7)
    assert first.weight_lbs == 11 and first.duration_s is None
    assert second.weight_lbs == 8
    assert second.duration_s == pytest.approx(120)  # 08:04 -> 08:06


def test_lr4_detect_without_weight_and_open_segment() -> None:
    events = [
        lr4_event(t("2026-11-21T09:00:00"), Status.CAT_DETECTED),
        lr4_event(t("2026-11-21T09:09:00"), Status.CLEAN_CYCLE),
        lr4_event(t("2026-11-21T10:00:00"), Status.CAT_DETECTED),
        lr4_event(t("2026-11-21T10:01:00"), "Pet Weight Recorded: 11.2 lbs"),
    ]
    no_weight, open_visit = lr4_visits("LR4X", events, wait_minutes=7)
    assert no_weight.weight_lbs is None and no_weight.duration_s == 120
    assert open_visit.weight_lbs == 11.2 and open_visit.duration_s is None


def test_lr4_unfinished_detection_waits_for_its_weigh_in() -> None:
    detected = [lr4_event(t("2026-11-21T10:00:00"), Status.CAT_DETECTED)]
    # Not weighed and not cycled yet: nothing to store, and the caller should
    # fetch again from the detection.
    assert lr4_visits("LR4X", detected, wait_minutes=7) == []
    assert lr4_open_since(detected) == t("2026-11-21T10:00:00")

    finished = detected + [
        lr4_event(t("2026-11-21T10:01:00"), "Pet Weight Recorded: 11.2 lbs"),
        lr4_event(t("2026-11-21T10:09:00"), Status.CLEAN_CYCLE),
    ]
    (visit,) = lr4_visits("LR4X", finished, wait_minutes=7)
    assert visit.timestamp == t("2026-11-21T10:01:00") and visit.duration_s == 120
    assert lr4_open_since(finished) is None


def test_store_keeps_the_longer_duration_estimate(tmp_path) -> None:
    store = Store(tmp_path / "smartcat.db")
    ts = t("2026-11-21T10:01:00")
    # A fetch that missed the detection estimates the visit too short.
    store.upsert_visits([Visit("LR4X", ts, 11.2, 60.0, "lr4", raw={"start": "late"})])
    store.upsert_visits([Visit("LR4X", ts, 11.2, 120.0, "lr4", raw={"start": "early"})])
    store.upsert_visits([Visit("LR4X", ts, 11.2, None, "lr4")])
    store.upsert_visits([Visit("LR4X", ts, 11.2, 90.0, "lr4", raw={"start": "mid"})])
    (visit,) = store.visits()
    assert visit.duration_s == 120
    assert visit.raw == {"start": "early"}


def test_lr4_cycle_too_late_gives_no_duration() -> None:
    events = [
        lr4_event(t("2026-11-21T09:00:00"), Status.CAT_DETECTED),
        lr4_event(t("2026-11-21T09:01:00"), "Pet Weight Recorded: 11 lbs"),
        lr4_event(t("2026-11-21T12:00:00"), Status.CLEAN_CYCLE),
    ]
    (visit,) = lr4_visits("LR4X", events, wait_minutes=7)
    assert visit.duration_s is None


def test_lr5_pet_visit_parsing_is_tolerant() -> None:
    records = [
        {"type": "CAT_DETECT", "timestamp": "2026-11-21T03:29:00Z"},
        {
            "type": "PET_VISIT",
            "timestamp": "2026-11-21T03:29:16.636Z",
            "petId": "PET-1",
            "weight": 1108,
            "duration": 95000,
        },
        {"type": "PET_VISIT", "createdAt": 1763695000, "data": {"petWeight": 10.5}},
        {"type": "PET_VISIT"},
    ]
    a, b = lr5_visits("LR5X", records)
    assert a.weight_lbs == 11.08 and a.whisker_pet_id == "PET-1" and a.duration_s == 95
    assert b.weight_lbs == 10.5 and b.duration_s is None


def test_lr5_falls_back_to_cat_detect() -> None:
    (visit,) = lr5_visits("LR5X", [{"type": "CAT_DETECT", "timestamp": "2026-11-21 03:29:00"}])
    assert visit.weight_lbs is None and visit.timestamp == t("2026-11-21T03:29:00")


# --- identification --------------------------------------------------------------

# Splashy's real weigh-ins, Nov 21-23 2026. Main Level (LR4) reads ~2 lb heavier
# than Basement (LR5); 6.49 / 8.59 / 9.03 / 9.7 are partial weigh-ins.
SPLASHY = [
    ("BASE", "2026-11-21T03:29:16", 11.08),
    ("BASE", "2026-11-21T05:34:33", 8.59),
    ("BASE", "2026-11-21T05:57:50", 10.54),
    ("MAIN", "2026-11-21T12:25:07", 6.49),
    ("BASE", "2026-11-21T16:14:48", 9.7),
    ("BASE", "2026-11-21T16:19:55", 11.07),
    ("BASE", "2026-11-21T22:23:55", 10.94),
    ("BASE", "2026-11-21T22:29:50", 11.48),
    ("BASE", "2026-11-22T11:17:44", 12.96),
    ("BASE", "2026-11-22T14:05:16", 11.48),
    ("MAIN", "2026-11-22T18:30:13", 12.89),
    ("MAIN", "2026-11-23T02:25:29", 13.09),
    ("BASE", "2026-11-23T03:49:43", 11.15),
    ("BASE", "2026-11-23T05:41:42", 10.83),
    ("MAIN", "2026-11-23T05:49:57", 13.13),
    ("BASE", "2026-11-23T11:00:52", 9.03),
    ("BASE", "2026-11-23T11:18:50", 10.27),
    ("BASE", "2026-11-23T19:14:34", 10.92),
]


def splashy_visits(repeat_days: int = 0) -> list[Visit]:
    """Splashy's real weigh-ins, repeated every 3 days with realistic jitter."""
    rng = random.Random(7)
    visits = [Visit(r, t(ts), w, 90.0, "x") for r, ts, w in SPLASHY]
    for day in range(1, repeat_days + 1):
        visits += [
            Visit(
                v.robot_serial,
                v.timestamp + timedelta(days=3 * day),
                round(v.weight_lbs + rng.uniform(-0.4, 0.4), 2),
                90.0,
                "x",
            )
            for v in visits[: len(SPLASHY)]
        ]
    return visits


def test_single_cat_gets_every_weighin_including_partials() -> None:
    cats = [Cat("splashy", "Splashy", seed_lbs=10.92, whisker_pet_id="PET-1")]
    assignments, ident = identify_all(cats, splashy_visits())
    assert all(a.cat_id == "splashy" for a in assignments.values())
    methods = {a.method for a in assignments.values()}
    assert "matched" in methods


def test_robot_offset_is_learned_and_not_a_new_cat() -> None:
    cats = [Cat("splashy", "Splashy", seed_lbs=10.92)]
    visits = splashy_visits(repeat_days=8)
    _, ident = identify_all(cats, visits)
    model = ident.models["splashy"]
    assert model.center("MAIN") == pytest.approx(13.1, abs=0.2)
    assert model.center("BASE") == pytest.approx(11.0, abs=0.3)
    assert ident.new_cat_candidate(visits[-1].timestamp) is None


def test_new_cat_is_suspected_then_separated_once_added() -> None:
    cats = [Cat("splashy", "Splashy", seed_lbs=10.92)]
    visits = splashy_visits(repeat_days=4)
    start = visits[-1].timestamp + timedelta(hours=1)
    rng = random.Random(4)
    kitten = [
        Visit("BASE", start + timedelta(hours=7 * i), round(6.0 + rng.uniform(-0.2, 0.2), 2), 60.0, "x")
        for i in range(16)
    ]
    _, ident = identify_all(cats, visits + kitten)
    candidate = ident.new_cat_candidate(kitten[-1].timestamp)
    assert candidate is not None
    assert candidate.median_lbs == pytest.approx(6.0, abs=0.2)
    assert candidate.count >= 8 and candidate.days >= 4
    assert candidate.first_seen == kitten[0].timestamp

    cats.append(Cat("kitten", "Kitten", seed_lbs=candidate.median_lbs, active_from=candidate.first_seen))
    assignments, ident = identify_all(cats, visits + kitten)
    assert all(assignments[v.key].cat_id == "kitten" for v in kitten)
    # Splashy's history before the kitten arrived is untouched.
    assert all(assignments[v.key].cat_id == "splashy" for v in visits)
    assert ident.new_cat_candidate(kitten[-1].timestamp) is None


def test_pet_id_wins_and_weightless_visits_are_assumed_for_single_cat() -> None:
    cats = [Cat("splashy", "Splashy", 11.0, "PET-1"), Cat("other", "Other", 7.0, "PET-2", t("2026-01-01T00:00:00"))]
    v1 = Visit("BASE", t("2026-11-21T00:00:00"), 11.0, None, "lr5", "PET-2")
    v2 = Visit("BASE", t("2026-11-21T01:00:00"), None, None, "lr5")
    assignments, _ = identify_all(cats, [v1, v2])
    assert assignments[v1.key].cat_id == "other" and assignments[v1.key].method == "pet_id"
    assert assignments[v2.key].cat_id is None  # two cats, no weight

    assignments, _ = identify_all(cats[:1], [v2])
    assert assignments[v2.key].method == "assumed"


def test_object_far_from_any_cat_is_unknown() -> None:
    cats = [Cat("splashy", "Splashy", 11.0)]
    v = Visit("BASE", t("2026-11-21T00:00:00"), 25.0, None, "x")
    assignments, _ = identify_all(cats, [v])
    assert assignments[v.key].cat_id is None


# --- analytics -----------------------------------------------------------------------


def steady_history(days: int, per_day: int, now: datetime, weight: float = 11.0) -> list[Visit]:
    visits = []
    for d in range(days, 0, -1):
        for i in range(per_day):
            ts = now - timedelta(days=d) + timedelta(hours=3 + i * 5)
            visits.append(Visit("BASE", ts, weight, 80.0 + i, "x"))
    return visits


def test_insights_normal_then_frequency_spike() -> None:
    now = datetime(2026, 11, 23, 20, 0, tzinfo=TZ).astimezone(UTC)
    visits = steady_history(30, 4, now)
    cats = [Cat("splashy", "Splashy", 11.0)]
    assignments, _ = identify_all(cats, visits)
    insights = cat_insights("splashy", visits, assignments, now, TZ)
    assert insights.status == "normal"
    assert insights.baseline_mean == pytest.approx(4.0, abs=0.1)
    assert sum(insights.hourly_histogram) == 4 * 30 - 0  # all within 30 days
    assert insights.weight_lbs == pytest.approx(11.0)
    assert len(insights.daily_counts) == 14

    burst = [Visit("BASE", now - timedelta(minutes=10 * i), 11.0, 80.0, "x") for i in range(9)]
    assignments, _ = identify_all(cats, visits + burst)
    insights = cat_insights("splashy", visits + burst, assignments, now, TZ)
    assert insights.status == "frequency_high"


def test_insights_no_recent_visits_and_weight_loss() -> None:
    now = datetime(2026, 11, 23, 20, 0, tzinfo=TZ).astimezone(UTC)
    old = steady_history(60, 4, now - timedelta(days=30), weight=12.0)
    recent = steady_history(30, 4, now - timedelta(days=2), weight=11.0)
    visits = old + recent
    cats = [Cat("splashy", "Splashy", 12.0)]
    assignments, _ = identify_all(cats, visits)
    insights = cat_insights("splashy", visits, assignments, now, TZ)
    kinds = {a.kind for a in insights.anomalies}
    assert "no_recent_visits" in kinds
    assert "weight_loss" in kinds
    assert insights.status == "no_recent_visits"
    assert insights.weight_trend_lbs_per_week < 0


def test_switching_robots_is_not_a_weight_change() -> None:
    """Main Level reads Splashy ~13.1 lb, Basement ~11 lb (observed)."""
    now = datetime(2026, 11, 23, 20, 0, tzinfo=TZ).astimezone(UTC)

    def on(robot: str, weight: float, days: range) -> list[Visit]:
        return [
            Visit(robot, now - timedelta(days=d, hours=h), weight, 80.0, "x")
            for d in days
            for h in (2, 9, 15)
        ]

    def insights_for(visits: list[Visit]):
        assignments = {v.key: Assignment("splashy", 0.95, "pet_id") for v in visits}
        return cat_insights("splashy", visits, assignments, now, TZ)

    # Main Level for a month, then the Basement for a month: same cat, same weight.
    moved = insights_for(on("MAIN", 13.1, range(31, 60)) + on("BASE", 11.0, range(0, 29)))
    assert moved.weight_change_30d_pct is None
    assert not {"weight_loss", "weight_gain"} & {a.kind for a in moved.anomalies}
    assert moved.weight_trend_lbs_per_week in (None, 0)

    # Using both robots throughout, a real 1 lb loss is still found on each.
    lost = insights_for(
        on("MAIN", 13.1, range(31, 60))
        + on("MAIN", 12.1, range(0, 29))
        + on("BASE", 11.0, range(31, 60))
        + on("BASE", 10.0, range(0, 29))
    )
    assert lost.weight_change_30d_pct == pytest.approx(-8.4, abs=0.5)
    assert "weight_loss" in {a.kind for a in lost.anomalies}


def test_insights_insufficient_data() -> None:
    now = t("2026-11-23T20:00:00")
    visits = [Visit("BASE", now - timedelta(hours=2), 11.0, 60.0, "x")]
    assignments, _ = identify_all([Cat("s", "S", 11.0)], visits)
    insights = cat_insights("s", visits, assignments, now, TZ)
    assert insights.status == "insufficient_data"
    assert insights.visits_today == 1


def test_long_visit_detected() -> None:
    now = datetime(2026, 11, 23, 20, 0, tzinfo=TZ).astimezone(UTC)
    visits = steady_history(20, 4, now)
    visits.append(Visit("BASE", now - timedelta(hours=1), 11.0, 900.0, "x"))
    assignments, _ = identify_all([Cat("s", "S", 11.0)], visits)
    insights = cat_insights("s", visits, assignments, now, TZ)
    assert "long_visit" in {a.kind for a in insights.anomalies}


# --- forecasting --------------------------------------------------------------------


def drawer_series(now: datetime) -> list[LevelReading]:
    """Drawer emptied 5 days ago; 4 cycles/day; +3% per cycle."""
    readings = [
        LevelReading("MAIN", now - timedelta(days=9), 70.0, 90.0, 100),
        LevelReading("MAIN", now - timedelta(days=5, hours=1), 82.0, 88.0, 104),
        LevelReading("MAIN", now - timedelta(days=5), 0.0, 88.0, 104),  # emptied
    ]
    for i in range(1, 21):
        readings.append(
            LevelReading(
                "MAIN", now - timedelta(days=5) + timedelta(hours=6 * i), 3.0 * i, 88.0 - 0.5 * i, 104 + i
            )
        )
    return readings


def test_waste_forecast_from_cycles() -> None:
    now = t("2026-11-23T20:00:00")
    readings = drawer_series(now)
    rate = cycles_per_day(readings, now)
    # 4 cycles in the 4 days before the reset, then 20 in 5 days.
    assert rate == pytest.approx(24 / 9, rel=0.01)
    fc = forecast_level(readings, waste=True, threshold=80, now=now, cycle_rate=rate)
    assert fc.method == "cycles"
    assert fc.current == 60.0
    assert fc.rate_per_cycle == pytest.approx(3.0)
    # 20 points left at ~3%/cycle * ~4 cycles/day = ~1.7 days.
    assert fc.days_remaining == pytest.approx(20 / (3 * rate), rel=0.05)
    assert fc.period_start == now - timedelta(days=5)


def test_litter_forecast() -> None:
    now = t("2026-11-23T20:00:00")
    readings = drawer_series(now)
    fc = forecast_level(readings, waste=False, threshold=70, now=now, cycle_rate=4.0)
    assert fc.rate_per_cycle == pytest.approx(-0.5)
    assert fc.current == 78.0
    assert fc.days_remaining == pytest.approx(8 / 2.0, rel=0.01)


def test_forecast_uses_prior_period_right_after_reset_and_reports_reached() -> None:
    now = t("2026-11-23T20:00:00")
    # Earlier period: +3% per cycle. Drawer emptied, then one cycle since.
    readings = [
        LevelReading("MAIN", now - timedelta(days=3, hours=h), 60.0 + 3 * (3 - h), 90.0, 100 + 3 - h)
        for h in (3, 2, 1, 0)
    ] + [
        LevelReading("MAIN", now - timedelta(days=1), 0.0, 90.0, 103),
        LevelReading("MAIN", now, 3.0, 90.0, 104),
    ]
    fc = forecast_level(readings, waste=True, threshold=80, now=now, cycle_rate=4.0)
    assert fc.method == "prior_cycles"
    assert fc.rate_per_cycle == pytest.approx(3.0)

    full = [LevelReading("MAIN", now, 85.0, 90.0, 1)]
    fc = forecast_level(full, waste=True, threshold=80, now=now, cycle_rate=None)
    assert fc.method == "reached" and fc.eta == now


def test_forecast_without_cycle_counts_uses_time() -> None:
    now = t("2026-11-23T20:00:00")
    readings = [
        LevelReading("B", now - timedelta(days=4 - d), 10.0 * d, None, None) for d in range(5)
    ]
    fc = forecast_level(readings, waste=True, threshold=80, now=now, cycle_rate=None)
    assert fc.method == "time"
    assert fc.days_remaining == pytest.approx(4.0)


def test_forecast_unknown_without_data() -> None:
    fc = forecast_level([], waste=True, threshold=80, now=t("2026-11-23T20:00:00"), cycle_rate=None)
    assert fc.eta is None and fc.method == "unknown"


# --- store ------------------------------------------------------------------------------


def test_store_roundtrip(tmp_path) -> None:
    store = Store(tmp_path / "smartcat.db")
    v = Visit("MAIN", t("2026-11-21T12:25:07"), 6.49, None, "lr4", raw={"start": "x"})
    assert store.upsert_visits([v]) == [v]
    # A re-fetch fills in the duration (see also the longer-estimate test).
    v2 = Visit("MAIN", v.timestamp, 6.49, 315.0, "lr4")
    assert store.upsert_visits([v2]) == []
    (loaded,) = store.visits()
    assert loaded.duration_s == 315.0 and loaded.raw == {"start": "x"}

    cat = Cat("splashy", "Splashy", 10.9, "PET-1", t("2026-01-01T00:00:00"))
    store.save_cat(cat)
    assert store.cats() == [cat]
    assert store.delete_cat("splashy") and store.cats() == []

    r = LevelReading("MAIN", t("2026-11-21T00:00:00"), 24.0, 90.0, 7)
    assert store.add_level(r)
    assert not store.add_level(LevelReading("MAIN", t("2026-11-21T01:00:00"), 24.0, 90.0, 7))
    assert store.levels("MAIN") == [r]

    store.set_meta("cursor:MAIN", "123")
    assert store.get_meta("cursor:MAIN") == "123"
    store.clear_meta_prefix("cursor:")
    assert store.get_meta("cursor:MAIN") is None
    assert store.delete_visits_before(t("2027-01-01T00:00:00")) == 1
    store.close()


def test_new_cat_inside_partial_band_is_detected_by_emergence() -> None:
    """A ~9 lb cat overlaps Splashy's partial weigh-ins; only its sudden appearance gives it away."""
    cats = [Cat("splashy", "Splashy", seed_lbs=11.0)]
    rng = random.Random(11)
    start = t("2026-09-01T00:00:00")
    visits = []
    for d in range(40):
        for h in (2, 8, 14, 20):
            ts = start + timedelta(days=d, hours=h)
            # 1 in 8 of Splashy's weigh-ins is a partial around 8.5-9.5 lb.
            w = rng.uniform(8.5, 9.5) if rng.random() < 0.125 else rng.gauss(11.0, 0.25)
            visits.append(Visit("BASE", ts, round(w, 2), 60.0, "x"))
    _, ident = identify_all(cats, visits)
    assert ident.new_cat_candidate(visits[-1].timestamp) is None

    arrival = start + timedelta(days=40)
    newcomer = [
        Visit("BASE", arrival + timedelta(hours=6 * i + 3), round(rng.gauss(9.0, 0.15), 2), 60.0, "x")
        for i in range(24)
    ]
    _, ident = identify_all(cats, visits + newcomer)
    candidate = ident.new_cat_candidate(newcomer[-1].timestamp)
    assert candidate is not None
    assert candidate.median_lbs == pytest.approx(9.0, abs=0.3)
    assert candidate.first_seen >= arrival - timedelta(days=2)
