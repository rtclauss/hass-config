"""Regression tests for the Tesla charge planner's calendar trip selection.

Background #1 (flights): a "flight to Atlanta" (or any far-destination flight)
on the calendar used to drive `binary_sensor.upcoming_trip_charging` on,
because the Waze distance to the arrival city is huge. With the
`>= 90 mi -> 100%` rule that pinned the home Tesla to a 100% charge while the
car never left the garage. The fix reuses the same flight-recognition rules
that travel detection uses (packages/trips.yaml) via a shared Jinja macro in
custom_templates/flight.jinja, applied while building each candidate event.

Background #2 (all-day events shadowing real events): `binary_sensor.
upcoming_trip_charging` used to read each source calendar's own pinned
"current event" attribute (`state_attr(calendar, 'start_time'/'message')`).
HA calendar entities only ever expose ONE such event, and while a same-day
all-day event (e.g. a recurring "Replace Contacts" reminder) is active it
pins that attribute for the whole day — so a real timed event later that same
day (e.g. a 10am dentist appointment) was invisible to the planner. The fix
enumerates every event via `calendar.get_events` instead, and drops all-day
events from candidacy entirely.

Background #3 (soonest-wins vs furthest-wins): the old selection picked
whichever candidate calendar's event started soonest, and charge limit was
sized off a single Waze sensor for that one destination. The planner now
scores every real (non-flight, non-all-day, in-horizon) candidate's driving
distance individually, excludes anything under the configurable "local trip"
neighborhood radius (`input_number.tesla_local_trip_threshold_mi`) entirely,
and sizes the charge limit off the FURTHEST qualifying event of the day while
still timing departure/preconditioning off the soonest qualifying event.
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


def test_charge_planner_uses_shared_flight_macro_when_building_candidates() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    # The macro is imported once, while building the combined candidate list,
    # and applied to each of the three candidate sources (personal loop,
    # curling loop, work check).
    assert text.count("{% from 'flight.jinja' import skip_charging_event %}") == 1
    assert text.count(
        "{% set should_skip_charging_event = skip_charging_event | as_function %}"
    ) == 1
    assert text.count("should_skip_charging_event(summary, description, location)") == 2
    assert text.count(
        "should_skip_charging_event(work_message, work_description, work_location)"
    ) == 1

    # The old bare per-calendar nocharge checks are gone; the macro now owns
    # both flight and nocharge exclusion so every source stays consistent.
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


def test_candidate_events_exclude_all_day_entries() -> None:
    # The original bug: a recurring all-day "Replace Contacts" reminder pinned
    # calendar.ryan_claussen's single native start_time/message attribute for
    # the whole day, hiding a real same-day timed event (a 10am dentist
    # appointment). The fix enumerates every event via calendar.get_events and
    # drops all-day events from candidacy before anything else runs.
    text = CAR_PATH.read_text(encoding="utf-8")
    candidates_block = re.search(
        r"candidates_json: >-\n(.*?)\n      - variables:\n          candidates: ",
        text,
        re.DOTALL,
    )
    assert candidates_block is not None
    block = candidates_block.group(1)

    assert block.count("not all_day and not should_skip_charging_event(") == 2
    assert "not work_all_day and not should_skip_charging_event(" in block
    assert block.count("{% set all_day = ('T' not in (start_raw | string)) %}") == 2


def test_trip_sensor_no_longer_reads_each_calendars_single_pinned_attribute() -> None:
    # The old bug mechanism: state_attr(calendar, 'start_time'/'message') only
    # ever sees ONE event per calendar. Selection must now come from full
    # calendar.get_events event lists instead.
    text = CAR_PATH.read_text(encoding="utf-8")
    trip_sensor_block = re.search(
        r"  - trigger:\n(.*?)\n    binary_sensor:\n      - name: upcoming_trip_charging",
        text,
        re.DOTALL,
    )
    assert trip_sensor_block is not None
    block = trip_sensor_block.group(1)

    assert "action: calendar.get_events" in block
    assert "entity_id: calendar.ryan_claussen" in block
    assert "entity_id: calendar.curling" in block
    assert "state_attr('calendar.ryan_claussen', 'start_time')" not in block
    assert "state_attr('calendar.curling', 'start_time')" not in block


def test_waze_lookup_failure_degrades_a_candidate_to_zero_distance() -> None:
    # A Waze API hiccup for one candidate's address must not crash the whole
    # sensor or leave a stale distance from a previous loop iteration around —
    # each iteration resets to 0 before attempting its own lookup, and the
    # service call tolerates failure.
    text = CAR_PATH.read_text(encoding="utf-8")
    repeat_block = re.search(
        r"      - repeat:\n(.*?)\n      - variables:\n          trip_plan_json:",
        text,
        re.DOTALL,
    )
    assert repeat_block is not None
    block = repeat_block.group(1)

    assert "candidate_waze_result: null" in block
    assert "candidate_distance_mi: 0" in block
    assert "candidate_duration_min: 0" in block
    assert "action: waze_travel_time.get_travel_times" in block
    assert "continue_on_error: true" in block


def test_charge_limit_is_sized_off_the_furthest_qualifying_event() -> None:
    # Distance for charge planning must come from the furthest qualifying
    # candidate, timing must come from the soonest qualifying candidate, and
    # both must be sourced from the new trigger-based sensor's own attributes
    # rather than the legacy passive sensor.waze_next_trip_distance.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert (
        "{% set trip_distance_mi = state_attr('binary_sensor.upcoming_trip_charging', 'distance_mi') | float(default=0) %}"
        in text
    )
    assert (
        "{% set trip_duration_raw = state_attr('binary_sensor.upcoming_trip_charging', 'duration_min') %}"
        in text
    )
    assert "'distance_mi': ns2.furthest.distance_mi," in text
    assert "'duration_min': ns2.next.duration_min," in text
    assert "state_attr('sensor.waze_next_trip_distance'" not in text


def test_local_trip_threshold_helper_gates_candidacy() -> None:
    # Events inside the "neighborhood" (e.g. a nearby errand) must never
    # become a qualifying trip candidate at all, regardless of how soon they
    # start — they should not drive charge limit or preconditioning.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "tesla_local_trip_threshold_mi:" in text
    assert "name: Tesla Local Trip Threshold" in text
    assert "initial: 10" in text
    assert "unit_of_measurement: mi" in text
    assert (
        "states('input_number.tesla_local_trip_threshold_mi') | float(default=10)"
        in text
    )
    assert "{% if c.distance_mi >= local_trip_threshold_mi %}" in text


def test_tesla_departure_planner_recomputes_when_trip_distance_changes() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")
    planner_block = re.search(
        r"  - id: tesla_departure_planner_apply\n(.*?)\n  - id: tesla_departure_schedule_cleanup",
        text,
        re.DOTALL,
    )
    assert planner_block is not None

    # The passive integration sensor is no longer authoritative for planning;
    # the planner now reacts to the new sensor's own distance_mi attribute.
    assert "entity_id: sensor.waze_next_trip_distance" not in planner_block.group(1)
    assert "attribute: distance_mi" in planner_block.group(1)
    assert "entity_id: binary_sensor.upcoming_trip_charging" in planner_block.group(1)
    assert "id: trip_details_change" in planner_block.group(1)


# ---------------------------------------------------------------------------
# Behavioral mirror of the trip_plan_json selection algorithm
# (packages/car.yaml, the final `variables: trip_plan_json` step of the
# upcoming_trip_charging trigger-based sensor). Kept in lockstep so the
# furthest-wins/neighborhood-exclusion rules are exercised without rendering
# Jinja in CI, matching the existing flight-macro mirror pattern above.
# ---------------------------------------------------------------------------


def _select_trip_plan(candidates: list[dict], local_trip_threshold_mi: float = 10) -> dict:
    qualifying = [c for c in candidates if c["distance_mi"] >= local_trip_threshold_mi]
    if not qualifying:
        return {
            "entry": "",
            "start_time": "",
            "all_day": False,
            "location": "",
            "distance_mi": 0,
            "duration_min": 0,
            "furthest_entry": "",
            "active": False,
        }
    next_candidate = min(qualifying, key=lambda c: c["start"])
    furthest_candidate = max(qualifying, key=lambda c: c["distance_mi"])
    return {
        "entry": f"{next_candidate['source']}: {next_candidate['message']}",
        "start_time": next_candidate["start"],
        "all_day": False,
        "location": next_candidate["location"],
        "distance_mi": furthest_candidate["distance_mi"],
        "duration_min": next_candidate["duration_min"],
        "furthest_entry": f"{furthest_candidate['source']}: {furthest_candidate['message']}",
        "active": True,
    }


def test_furthest_event_of_the_day_drives_the_charge_limit() -> None:
    # The reported request: two local errands under the neighborhood radius
    # plus one 100 mi trip later the same day must charge to the 100 mi trip,
    # not whichever event happens to start soonest.
    candidates = [
        {
            "source": "Personal",
            "message": "Grocery run",
            "start": "2026-09-16T09:00:00-05:00",
            "location": "Local grocery store",
            "distance_mi": 3,
            "duration_min": 8,
        },
        {
            "source": "Personal",
            "message": "Pick up dry cleaning",
            "start": "2026-09-16T11:00:00-05:00",
            "location": "Local dry cleaner",
            "distance_mi": 5,
            "duration_min": 10,
        },
        {
            "source": "Personal",
            "message": "Think Loan Closing",
            "start": "2026-09-16T13:00:00-05:00",
            "location": "Title company, Minneapolis, MN",
            "distance_mi": 100,
            "duration_min": 40,
        },
    ]

    plan = _select_trip_plan(candidates)

    assert plan["active"] is True
    assert plan["distance_mi"] == 100
    assert plan["furthest_entry"] == "Personal: Think Loan Closing"
    # Only one candidate qualifies here, so it is also the soonest.
    assert plan["entry"] == "Personal: Think Loan Closing"


def test_departure_timing_follows_the_soonest_qualifying_event_even_when_a_later_one_is_further() -> None:
    # Dentist (soonest, real trip) and a later Loan Closing (furthest) both
    # qualify. Preconditioning must still target the Dentist departure time,
    # while the charge limit reflects the Loan Closing distance.
    candidates = [
        {
            "source": "Personal",
            "message": "Dentist",
            "start": "2026-09-16T10:00:00-05:00",
            "location": "Zumbro View Dental, Rochester, MN",
            "distance_mi": 69.6,
            "duration_min": 68,
        },
        {
            "source": "Personal",
            "message": "Think Loan Closing",
            "start": "2026-09-16T13:00:00-05:00",
            "location": "Title company, Minneapolis, MN",
            "distance_mi": 100,
            "duration_min": 40,
        },
    ]

    plan = _select_trip_plan(candidates)

    assert plan["entry"] == "Personal: Dentist"
    assert plan["start_time"] == "2026-09-16T10:00:00-05:00"
    assert plan["duration_min"] == 68
    assert plan["distance_mi"] == 100
    assert plan["furthest_entry"] == "Personal: Think Loan Closing"


def test_all_local_events_never_produce_an_active_plan() -> None:
    candidates = [
        {
            "source": "Personal",
            "message": "Grocery run",
            "start": "2026-09-16T09:00:00-05:00",
            "location": "Local grocery store",
            "distance_mi": 3,
            "duration_min": 8,
        },
    ]

    plan = _select_trip_plan(candidates)

    assert plan["active"] is False
    assert plan["entry"] == ""
    assert plan["distance_mi"] == 0


def test_no_location_event_is_treated_as_local_not_a_trip() -> None:
    # An event with a blank location (e.g. an all-day reminder that slipped
    # through, or a same-day note with no address) scores 0 mi and is
    # therefore excluded the same way a genuinely nearby errand is.
    candidates = [
        {
            "source": "Personal",
            "message": "Replace Contacts",
            "start": "2026-09-16T00:00:00-05:00",
            "location": "",
            "distance_mi": 0,
            "duration_min": 0,
        },
        {
            "source": "Personal",
            "message": "Dentist",
            "start": "2026-09-16T10:00:00-05:00",
            "location": "Zumbro View Dental, Rochester, MN",
            "distance_mi": 69.6,
            "duration_min": 68,
        },
    ]

    plan = _select_trip_plan(candidates)

    assert plan["entry"] == "Personal: Dentist"
    assert plan["distance_mi"] == 69.6
