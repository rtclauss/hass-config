"""Regression tests for the planner's day-total reporting (issue #1202).

The charge tier is sized off the furthest qualifying event, so on a day with
several qualifying trips the other legs were invisible: the summary reported
only the furthest leg's one-way distance. For a day holding a 70 mi afternoon
appointment and a 17 mi evening event, that read "Distance 70 mi" against
~174 mi of actual driving.

This adds reporting ONLY. The charge tiers are deliberately untouched:
Supercharging is available, so under-charging costs a short stop rather than a
missed appointment, while the 2019 NCA pack makes routine 100% charging the
thing to avoid. Over-charging has a real cumulative cost and under-charging a
small recoverable one, so the planner informs and leaves the decision to the
owner.

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
    assert "states('input_number.tesla_usable_range_mi') | float(default=240)" in text

    # No `initial:` on the helper. input_number `initial:` FORCES the value at
    # every restart, so a calibration would be silently discarded and the
    # advisory would quietly revert to the default range (Codex P2 on #1203).
    # The first-use default comes from the template fallback above instead.
    block = text[text.index("tesla_usable_range_mi:") :]
    block = block[: block.index("tesla_degraded_travel_min:")]
    # Ignore comment lines: the block explains why `initial:` is absent.
    keys = [ln for ln in block.splitlines() if not ln.strip().startswith("#")]
    assert not any("initial:" in ln for ln in keys), (
        "usable-range calibration resets on restart"
    )


def test_degraded_travel_fallback_also_persists() -> None:
    # Same defect, same fix: this helper is documented as calibrated from
    # observed drives, so it must survive a restart too.
    text = CAR_PATH.read_text(encoding="utf-8")

    start = text.index("tesla_degraded_travel_min:")
    block = text[start : start + 400]
    assert "name: Tesla Degraded Travel Fallback" in block
    keys = [ln for ln in block.splitlines() if not ln.strip().startswith("#")]
    assert not any("initial:" in ln for ln in keys), (
        "degraded-travel calibration resets on restart"
    )
    assert (
        "states('input_number.tesla_degraded_travel_min') | float(default=60)" in text
    )


def test_no_live_itinerary_details_in_public_planner_files() -> None:
    # Codex P1 on PR #1203. specs/private_runtime_config.allium keeps exact
    # travel histories out of public Git and requires synthetic values in
    # documentation and fixtures. Worked examples must be invented and undated.
    # This is the second privacy slip of this kind in the planner work (live
    # coordinates were the first, on PR #1199), hence a standing guard.
    #
    # Deliberately matches CATEGORY shapes rather than the real destinations:
    # listing those here would reproduce in a public file exactly what the
    # guard exists to keep out.
    #
    # Generic appointment types ("Dentist", "Example Dental, Sample City, ST")
    # are an established synthetic convention in this repo and are NOT flagged.
    # What identifies a real trip is a date plus a real place, so those are the
    # shapes guarded here.
    import re

    patterns = {
        "dated itinerary": re.compile(r"\b20\d\d-\d\d-\d\d\b"),
        "street address": re.compile(
            r"\b\d+\s+\w+(\s+\w+)*\s+(Ave|Avenue|St|Street|Ln|Lane|Rd|Road|Blvd|Way|Dr|Drive)\b"
        ),
    }
    for rel in (
        "docs/tesla_departure_planner.md",
        "packages/car.yaml",
        "private_templates/car.yaml.tmpl",
        "tests/test_issue_tesla_planner_day_total.py",
        "tests/test_issue_tesla_planner_waze_geocode.py",
        "tests/test_issue_tesla_scheduled_departure_params.py",
    ):
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            match = pattern.search(text)
            assert match is None, (
                f"{rel} carries {label} detail: {match.group(0)!r} - "
                "use an invented, undated example instead"
            )
