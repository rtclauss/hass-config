"""Regression tests for the Tesla charge planner ignoring flights.

Background: a "flight to Atlanta" (or any far-destination flight) on the
calendar used to drive `binary_sensor.upcoming_trip_charging` on, because the
Waze distance to the arrival city is huge. With the `>= 90 mi -> 100%` rule that
pinned the home Tesla to a 100% charge while the car never left the garage.

The fix reuses the same flight-recognition rules that travel detection uses
(packages/trips.yaml) via a shared Jinja macro in custom_templates/flight.jinja,
and applies it to every block of the charge-planner trip sensor so flights are
excluded from charge planning regardless of origin airport.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PATH = ROOT / "packages" / "car.yaml"
FLIGHT_MACRO_PATH = ROOT / "custom_templates" / "flight.jinja"


def _looks_like_flight(summary: str, description: str = "", location: str = "") -> bool:
    """Mirror of the looks_like_flight macro in custom_templates/flight.jinja.

    Kept in lockstep with the Jinja rules (and with parse_flight_signals in
    test_trips_flight_classification.py) so the planner's flight exclusion is
    exercised without rendering Jinja in CI.
    """
    summary_text = summary or ""
    summary_lower = summary_text.lower()
    trip_text = " ".join(
        part for part in [summary_text, description or "", location or ""]
    ).lower()

    route_summary = "→" in summary_text
    named_flight = summary_lower.startswith("flight to ") or (
        summary_lower.startswith("flight: ") and " to " in summary_lower
    )
    itinerary_marker = any(
        marker in trip_text
        for marker in (
            "synced by flighty",
            "created from an email you received in gmail",
            "booking code:",
            "flight time ",
        )
    )
    return route_summary or named_flight or itinerary_marker


def _skip_charging_event(summary: str, description: str = "", location: str = "") -> bool:
    """Mirror of the skip_charging_event macro: flight OR manual nocharge tag."""
    return _looks_like_flight(summary, description, location) or (
        "nocharge" in (description or "").lower()
    )


def test_flight_macro_file_defines_shared_recognition_macros() -> None:
    text = FLIGHT_MACRO_PATH.read_text(encoding="utf-8")

    assert "macro looks_like_flight(summary, description='', location='', returns=none)" in text
    assert "macro skip_charging_event(summary, description='', location='', returns=none)" in text
    assert "{%- do returns(route_summary or named_flight or itinerary_marker) -%}" in text
    assert "{%- set flight_classifier = looks_like_flight | as_function -%}" in text
    assert "{%- do returns(is_flight or is_nocharge) -%}" in text
    # The detection rules must match the travel-detection logic in trips.yaml.
    assert "'→' in summary_text" in text
    assert "summary_lower.startswith('flight to ')" in text
    assert "summary_lower.startswith('flight: ') and ' to ' in summary_lower" in text
    assert "synced by flighty" in text
    assert "created from an email you received in gmail" in text
    assert "booking code:" in text
    assert "flight time " in text
    # The manual nocharge opt-out is still honored by the shared macro.
    assert "nocharge" in text


def test_charge_planner_uses_shared_flight_macro_in_every_trip_block() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    # The macro is imported and applied in all four template blocks
    # (state + entry + start_time + all_day) of upcoming_trip_charging.
    assert text.count("{% from 'flight.jinja' import skip_charging_event %}") == 4
    assert text.count(
        "{% set should_skip_charging_event = skip_charging_event | as_function %}"
    ) == 4
    assert text.count("should_skip_charging_event(state_attr('calendar.ryan_claussen'") == 4
    assert text.count("should_skip_charging_event(state_attr('binary_sensor.work_trip_today'") == 4
    assert text.count("should_skip_charging_event(state_attr('calendar.curling'") == 4
    assert "| trim | lower == 'true'" not in text

    # The old bare per-calendar nocharge checks are gone; the macro now owns
    # both flight and nocharge exclusion so every block stays consistent.
    assert "'nocharge' not in personal_description" not in text
    assert "'nocharge' not in work_description" not in text
    assert "'nocharge' not in curling_description" not in text


def test_flight_events_are_excluded_from_charge_planning() -> None:
    # Outbound "flight to Atlanta" style event (the original bug).
    assert _skip_charging_event("Flight to Atlanta (DL 2819)", "Synced by Flighty") is True
    # Route-arrow itineraries, including legs that do not depart from MSP.
    assert _skip_charging_event("✈ CMH→SLC • DL 1234", "Synced by Flighty") is True
    assert _skip_charging_event("✈ SFO→MSP • DL 5678", "Synced by Flighty") is True
    # Itinerary markers alone are enough.
    assert _skip_charging_event("Trip", "Created from an email you received in Gmail") is True
    # Manual opt-out still works.
    assert _skip_charging_event("Road trip to Duluth", "nocharge please") is True


def test_real_drives_still_count_toward_charge_planning() -> None:
    # A genuine long drive with no flight signals and no nocharge tag must
    # still be eligible so the planner can raise the charge limit.
    assert _skip_charging_event("Curling bonspiel", location="Brookings, SD") is False
    assert _skip_charging_event("Visit the cabin", "Up north for the weekend") is False


def test_upcoming_trip_charging_state_still_gates_on_waze_distance() -> None:
    # The flight exclusion must not disturb the existing distance gate.
    text = CAR_PATH.read_text(encoding="utf-8")
    state_block = re.search(
        r"state: >-\n(.*?)\n      - default_entity_id: binary_sensor\.tesla_daily_plan_active",
        text,
        re.DOTALL,
    )
    assert state_block is not None
    assert (
        '{{ ns.eligible and (state_attr("sensor.waze_next_trip_distance", "distance") | int(0) > 45) }}'
        in state_block.group(1)
    )
