"""Regression tests for the planner's day-total reporting (issue #1202).

The charge tier is sized off the furthest qualifying event, so on a day with
several qualifying trips the other legs were invisible: the summary reported
only the furthest leg's one-way distance. On 2026-11-17 that read "Distance
70 mi" for a day holding a 70.9 mi dentist round trip plus a 16.7 mi curling
round trip — about 175 mi of driving.

This adds reporting ONLY. The charge tiers are deliberately untouched:
Supercharging is available on these routes, so under-charging costs a short
stop rather than a missed appointment, while the 2019 NCA pack makes routine
100% charging the thing to avoid. Over-charging has a real cumulative cost and
under-charging a small recoverable one, so the planner informs and leaves the
decision to the owner.

No surveyed project (EV Smart Charging, Teslemetry, Tesla Fleet) computes a
required charge level from trip distance, handles round trips or multi-trip
days, or applies a temperature derate — so these guarantees have no upstream
equivalent to defer to.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PATH = ROOT / "packages" / "car.yaml"


def test_day_total_sums_every_qualifying_event_as_a_round_trip() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert (
        "{% set ns2.day_round_trip_mi = ns2.day_round_trip_mi + (c.distance_mi * 2) %}"
        in text
    )
    assert "{% set ns2.trip_count = ns2.trip_count + 1 %}" in text
    # Accumulated only inside the qualifies branch, so an event inside the
    # local-trip threshold never contributes.
    qualifies_at = text.index("{% set qualifies = (c_located and not c_scored)")
    accumulate_at = text.index("ns2.day_round_trip_mi + (c.distance_mi * 2)")
    assert qualifies_at < accumulate_at


def test_day_total_is_exposed_on_the_sensor() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "day_round_trip_mi: >-" in text
    assert "trip_count: >-" in text
    assert "'day_round_trip_mi': ns2.day_round_trip_mi | round(1)," in text
    assert "'trip_count': ns2.trip_count," in text
    # Present on the inactive payload too, so consumers never see a gap.
    assert "'day_round_trip_mi': 0, 'trip_count': 0," in text


def test_day_total_appears_in_the_summary() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "' mi across ' ~ trip_count ~ ' trips (round trip each).'" in text
    assert "' mi round trip.'" in text


def test_a_degraded_day_total_is_reported_as_a_floor() -> None:
    # An unscored trip is counted but contributes no miles, so the figure is a
    # floor. It must not be stated as an exact total.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert (
        "{% set day_total_prefix = 'Day total at least ' if scoring_degraded"
        " else 'Day total ' %}" in text
    )


def test_shortfall_is_advised_and_never_changes_the_charge_limit() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    # The advisory exists and names the shortfall.
    assert "{% set tier_range_mi = usable_range_mi * (charge_limit / 100) %}" in text
    assert "so plan a charging stop or turn on the max-range override." in text

    # tier_range_mi is DERIVED from charge_limit, so the dependency runs one
    # way only. Pin that nothing reassigns charge_limit after it is read: any
    # `set charge_limit` after that point would create a feedback loop.
    derive_at = text.index("{% set tier_range_mi = usable_range_mi * (charge_limit / 100) %}")
    assert "{% set charge_limit" not in text[derive_at:], (
        "charge_limit is reassigned after the day-total advisory reads it"
    )

    # The advisory may only append to the summary string.
    advisory_region = text[derive_at : text.index("Never let a lost travel-time")]
    assert "{% set summary = summary ~" in advisory_region
    for forbidden in ("charge_limit =", "precondition =", "departure_time ="):
        assert forbidden not in advisory_region, (
            f"advisory mutates planner state: {forbidden}"
        )


def test_charge_limit_tiers_are_unchanged() -> None:
    # Pin the tier ladder itself, so a later edit cannot quietly escalate it.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "{% if has_upcoming_trip and trip_distance_mi >= 90 %}" in text
    assert text.count("{% set charge_limit = 100 %}") == 2  # long trip + override
    assert "{% elif alarm_enabled and not high_tariff %}" in text

    # No tier is keyed on the day total.
    tier_region = text[
        text.index("{% if has_upcoming_trip and trip_distance_mi >= 90 %}") :
        text.index("{% if manual_override %}")
    ]
    assert "day_round_trip_mi" not in tier_region
    assert "trip_count" not in tier_region


def test_usable_range_helper_is_a_fixed_calibrated_value() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "tesla_usable_range_mi:" in text
    assert "name: Tesla Usable Range At Full" in text
    assert "initial: 240" in text
    assert "states('input_number.tesla_usable_range_mi') | float(default=240)" in text
