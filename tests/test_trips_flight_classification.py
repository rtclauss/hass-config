from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


CENTRAL = ZoneInfo("America/Chicago")
HOME_CODES = {"MSP", "RST", "MINNEAPOLIS", "MINNEAPOLISSTPAUL", "ROCHESTER", "MINNESOTA"}
TRIPS_PATH = Path(__file__).resolve().parents[1] / "packages" / "trips.yaml"
MATRIX_PATH = Path(__file__).resolve().parents[1] / "docs" / "travel_detection_regression_matrix.md"


@dataclass(frozen=True)
class FlightSignals:
    looks_like_flight: bool
    named_flight: bool
    origin_code: str
    destination_code: str
    destination_name: str
    is_friend: bool


@dataclass(frozen=True)
class FallbackCandidate:
    summary: str
    start: datetime
    end: datetime
    vacation_name: str
    source_code: str
    source_label: str
    priority: int


def normalize_code(value: str) -> str:
    return re.sub(r"[^A-Za-z]", "", value).upper()


def parse_flight_signals(summary: str, description: str = "", location: str = "") -> FlightSignals:
    summary_text = summary or ""
    summary_lower = summary_text.lower()
    flight_text = " ".join(part for part in [summary_text, description or "", location or ""]).lower()

    route_summary = "→" in summary_text
    named_flight = summary_lower.startswith("flight to ") or (
        summary_lower.startswith("flight: ") and " to " in summary_lower
    )
    itinerary_marker = any(
        marker in flight_text
        for marker in (
            "synced by flighty",
            "created from an email you received in gmail",
            "booking code:",
            "flight time ",
        )
    )
    looks_like_flight = route_summary or named_flight or itinerary_marker

    origin_code = ""
    destination_name = ""
    destination_code = ""

    if route_summary:
        origin_part, destination_part = summary_text.split("→", 1)
        origin_code = normalize_code(origin_part)
        destination_name = destination_part.split("•", 1)[0].strip()
        destination_code = normalize_code(destination_name)
    elif summary_lower.startswith("flight to "):
        match = re.match(r"(?i)^flight to\s+(.+?)(?:\s+\(|\s+•|$)", summary_text)
        if match:
            destination_name = match.group(1).strip()
            destination_code = normalize_code(destination_name)
    elif summary_lower.startswith("flight: ") and " to " in summary_lower:
        match = re.match(r"(?i)^flight:\s+.+?\s+to\s+(.+?)(?:\s+\(|\s+•|$)", summary_text)
        if match:
            destination_name = match.group(1).strip()
            destination_code = normalize_code(destination_name)

    if not destination_name and destination_code and destination_code not in HOME_CODES:
        destination_name = destination_code

    return FlightSignals(
        looks_like_flight=looks_like_flight,
        named_flight=named_flight,
        origin_code=origin_code,
        destination_code=destination_code,
        destination_name=destination_name,
        is_friend="friend" in flight_text,
    )


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(CENTRAL)


def event_window(event: dict) -> tuple[datetime, datetime, bool, int]:
    start = iso(event["start"])
    end = iso(event["end"])
    is_all_day = "T" not in str(event["start"])
    duration_days = int((end - start).total_seconds() / 86400)
    return start, end, is_all_day, duration_days


def standalone_fallback_candidates(
    curling_events: list[dict],
    personal_events: list[dict],
    work_trip_events: list[dict],
    now: datetime,
) -> list[FallbackCandidate]:
    candidates: list[FallbackCandidate] = []

    for event in curling_events:
        start, end, is_all_day, duration_days = event_window(event)
        if end > now and is_all_day and duration_days > 2:
            summary = event.get("summary", "Curling")
            candidates.append(
                FallbackCandidate(summary, start, end, summary, "curling_block", "curling block", 4)
            )

    for event in personal_events:
        start, end, is_all_day, duration_days = event_window(event)
        text = " ".join(
            [
                event.get("summary", ""),
                event.get("description", ""),
                event.get("location", ""),
            ]
        ).lower()
        is_explicit_vacation = "#vacation" in text
        is_trip_block = is_all_day and duration_days > 1 and any(
            keyword in text for keyword in ("vacation", " trip", "travel", "out of town", "pto", "ooo")
        )
        if end > now and (is_explicit_vacation or is_trip_block):
            summary = event.get("summary", "Vacation")
            candidates.append(
                FallbackCandidate(
                    summary,
                    start,
                    end,
                    summary,
                    "explicit_vacation" if is_explicit_vacation else "all_day_trip_block",
                    "explicit vacation event" if is_explicit_vacation else "all-day trip block",
                    1 if is_explicit_vacation else 3,
                )
            )

    for event in work_trip_events:
        start, end, is_all_day, duration_days = event_window(event)
        text = " ".join(
            [
                event.get("summary", ""),
                event.get("description", ""),
                event.get("location", ""),
            ]
        ).lower()
        is_lodging = any(
            keyword in text
            for keyword in ("stay at", "hotel", "airbnb", "lodging", "resort", " inn", "check-in", "check out")
        )
        is_trip_block = is_all_day and duration_days > 1
        if end > now and (is_lodging or is_trip_block):
            summary = event.get("summary", "Work Trip")
            candidates.append(
                FallbackCandidate(
                    summary,
                    start,
                    end,
                    summary,
                    "lodging" if is_lodging else "all_day_trip_block",
                    "lodging span" if is_lodging else "all-day trip block",
                    0 if is_lodging else 3,
                )
            )

    return candidates


def best_standalone_fallback(
    curling_events: list[dict],
    personal_events: list[dict],
    work_trip_events: list[dict],
    now: datetime,
) -> FallbackCandidate | None:
    candidates = standalone_fallback_candidates(curling_events, personal_events, work_trip_events, now)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: (candidate.priority, candidate.start))


def best_paired_fallback(
    outbound_start: datetime,
    curling_events: list[dict],
    personal_events: list[dict],
    work_trip_events: list[dict],
    now: datetime,
) -> FallbackCandidate | None:
    candidates = standalone_fallback_candidates(curling_events, personal_events, work_trip_events, now)
    eligible = [
        candidate
        for candidate in candidates
        if candidate.end > outbound_start and candidate.start <= outbound_start + timedelta(days=3)
    ]
    if not eligible:
        return None

    def key(candidate: FallbackCandidate) -> tuple[int, int, float, datetime]:
        contains_outbound = candidate.start <= outbound_start <= candidate.end
        proximity = abs((candidate.start - outbound_start).total_seconds())
        return (candidate.priority, 0 if contains_outbound else 1, proximity, candidate.start)

    return min(eligible, key=key)


def build_vacation_plan(
    personal_events: list[dict],
    now: datetime,
    *,
    curling_events: list[dict] | None = None,
    work_trip_events: list[dict] | None = None,
) -> dict:
    curling_events = curling_events or []
    work_trip_events = work_trip_events or []
    travel_events = personal_events + work_trip_events
    standalone_fallback = best_standalone_fallback(curling_events, personal_events, work_trip_events, now)

    ignored_reason = "No qualifying travel itinerary or calendar trip block was found."
    outbound = None
    for event in travel_events:
        start_dt, _, _, _ = event_window(event)
        signals = parse_flight_signals(
            event.get("summary", ""),
            event.get("description", ""),
            event.get("location", ""),
        )
        is_home_origin = signals.origin_code in {"MSP", "RST"}
        is_home_destination = signals.destination_code in HOME_CODES
        outbound_priority = 0 if is_home_origin else 1 if signals.named_flight else 9

        if signals.looks_like_flight and signals.is_friend and is_home_destination:
            ignored_reason = "Ignored a friend itinerary arriving home."

        if (
            signals.looks_like_flight
            and not signals.is_friend
            and start_dt >= now - timedelta(hours=1)
            and signals.destination_name
            and not is_home_destination
            and outbound_priority < 9
        ):
            candidate = {
                "summary": event["summary"],
                "start": start_dt,
                "priority": outbound_priority,
                "destination_name": signals.destination_name,
            }
            if outbound is None or candidate["priority"] < outbound["priority"] or (
                candidate["priority"] == outbound["priority"] and candidate["start"] < outbound["start"]
            ):
                outbound = candidate

    if outbound is None:
        if standalone_fallback is None:
            return {
                "reason": "off",
                "decision_code": "off_no_candidate",
                "decision_summary": ignored_reason,
                "ignored_reason": ignored_reason,
            }
        return {
            "reason": "calendar",
            "decision_code": f"calendar_{standalone_fallback.source_code}",
            "decision_summary": f"Using standalone {standalone_fallback.source_label}.",
            "summary": standalone_fallback.summary,
            "start": standalone_fallback.start,
            "end": standalone_fallback.end,
            "return_summary": "",
            "vacation_name": standalone_fallback.vacation_name,
            "outbound_summary": "",
            "destination_name": standalone_fallback.vacation_name,
            "fallback_summary": standalone_fallback.summary,
            "fallback_source": standalone_fallback.source_label,
            "ignored_reason": "",
        }

    final_destination = outbound["destination_name"]
    return_home = None
    for event in travel_events:
        start_dt, _, _, _ = event_window(event)
        signals = parse_flight_signals(
            event.get("summary", ""),
            event.get("description", ""),
            event.get("location", ""),
        )
        is_home_destination = signals.destination_code in HOME_CODES
        if (
            signals.looks_like_flight
            and not signals.is_friend
            and signals.destination_name
            and not is_home_destination
            and outbound["start"] <= start_dt <= outbound["start"] + timedelta(days=2)
        ):
            final_destination = signals.destination_name
        if (
            signals.looks_like_flight
            and not signals.is_friend
            and is_home_destination
            and start_dt > outbound["start"]
        ):
            candidate = {"summary": event["summary"], "start": start_dt}
            if return_home is None or candidate["start"] < return_home["start"]:
                return_home = candidate

    if return_home is not None:
        return {
            "reason": "flight",
            "decision_code": "flight_return",
            "decision_summary": "Using outbound flight and booked return flight.",
            "summary": outbound["summary"],
            "start": outbound["start"],
            "end": return_home["start"] - timedelta(hours=2),
            "return_summary": return_home["summary"],
            "vacation_name": final_destination,
            "outbound_summary": outbound["summary"],
            "destination_name": final_destination,
            "fallback_summary": "",
            "fallback_source": "",
            "ignored_reason": "",
        }

    paired_fallback = best_paired_fallback(
        outbound["start"], curling_events, personal_events, work_trip_events, now
    )
    if paired_fallback is not None:
        return {
            "reason": "flight",
            "decision_code": f"flight_{paired_fallback.source_code}",
            "decision_summary": (
                f"Using outbound flight and {paired_fallback.source_label} because no return flight is booked."
            ),
            "summary": outbound["summary"],
            "start": outbound["start"],
            "end": paired_fallback.end,
            "return_summary": "",
            "vacation_name": final_destination or paired_fallback.vacation_name,
            "outbound_summary": outbound["summary"],
            "destination_name": final_destination or paired_fallback.vacation_name,
            "fallback_summary": paired_fallback.summary,
            "fallback_source": paired_fallback.source_label,
            "ignored_reason": "",
        }

    return {
        "reason": "off",
        "decision_code": "off_outbound_missing_end",
        "decision_summary": "Found an outbound flight, but no booked return or related fallback trip window.",
        "summary": "",
        "start": "",
        "end": "",
        "return_summary": "",
        "vacation_name": "",
        "outbound_summary": outbound["summary"],
        "destination_name": final_destination,
        "fallback_summary": "",
        "fallback_source": "",
        "ignored_reason": "No return flight or linked lodging, vacation event, or all-day trip block was found.",
    }


def test_generic_locations_do_not_look_like_flights() -> None:
    barber = parse_flight_signals(
        "Appointment with The Brewing Barber",
        location="3001 Hennepin Ave S, Minneapolis, MN 55408, United States",
    )
    dentist = parse_flight_signals(
        "Dentist Appointment",
        location="Mayo Clinic, Rochester, MN 55905, United States",
    )

    assert barber.looks_like_flight is False
    assert barber.destination_code == ""
    assert dentist.looks_like_flight is False
    assert dentist.destination_code == ""


def test_route_summaries_keep_departure_and_return_directions_distinct() -> None:
    outbound = parse_flight_signals("✈ MSP→CLT • DL 2819")
    return_home = parse_flight_signals("✈ CLT→MSP • DL 2820")

    assert outbound.origin_code == "MSP"
    assert outbound.destination_code == "CLT"
    assert outbound.destination_code not in HOME_CODES

    assert return_home.origin_code == "CLT"
    assert return_home.destination_code == "MSP"
    assert return_home.destination_code in HOME_CODES


def test_named_flights_extract_clean_destination_codes() -> None:
    direct = parse_flight_signals("flight to CLT (DL 2819)")
    verbose = parse_flight_signals("Flight: MSP TO CLT (DL 2819)")
    homebound = parse_flight_signals("Flight to Minnesota (DL 2819)")

    assert direct.destination_name == "CLT"
    assert direct.destination_code == "CLT"
    assert verbose.destination_name == "CLT"
    assert verbose.destination_code == "CLT"
    assert homebound.destination_name == "Minnesota"
    assert homebound.destination_code == "MINNESOTA"
    assert homebound.destination_code in HOME_CODES


def test_trips_package_avoids_case_sensitive_named_flight_splits() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")

    assert "summary.split('Flight to ', 1)" not in text
    assert "summary.split('Flight: ', 1)" not in text
    assert "flight_tail_lower = summary_lower[8:]" in text


def test_trips_package_exposes_vacation_plan_diagnostics_and_logging() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")

    assert "decision_code:" in text
    assert "decision_summary:" in text
    assert "fallback_summary:" in text
    assert "ignored_reason:" in text
    assert "alias: log_calendar_vacation_plan_diagnostics" in text
    assert "name: Travel detection" in text
    assert "attribute: decision_code" in text
    assert "continue_on_error: true\n        action: logbook.log" in text
    assert "not is_friend_itinerary and destination_code in ['MSP', 'MINNEAPOLIS', 'MINNEAPOLISSTPAUL', 'MINNESOTA']" in text
    assert "not is_friend_itinerary and destination_code in ['RST', 'ROCHESTER']" in text


def test_vacation_plan_ignores_barber_and_pairs_real_outbound_with_return() -> None:
    now = iso("2026-03-24T10:30:00-05:00")
    events = [
        {
            "summary": "Appointment with The Brewing Barber",
            "location": "3001 Hennepin Ave S, Minneapolis, MN 55408, United States",
            "start": "2026-03-24T11:40:00-05:00",
            "end": "2026-03-24T12:40:00-05:00",
        },
        {
            "summary": "✈ MSP→CLT • DL 2819",
            "description": "Synced by Flighty",
            "start": "2026-04-09T14:20:00-05:00",
            "end": "2026-04-09T17:00:00-05:00",
        },
        {
            "summary": "✈ CLT→MSP • DL 2820",
            "description": "Synced by Flighty",
            "start": "2026-04-13T15:35:00-05:00",
            "end": "2026-04-13T18:15:00-05:00",
        },
    ]

    plan = build_vacation_plan(events, now)

    assert plan["reason"] == "flight"
    assert plan["decision_code"] == "flight_return"
    assert plan["summary"] == "✈ MSP→CLT • DL 2819"
    assert plan["start"] == iso("2026-04-09T14:20:00-05:00")
    assert plan["end"] == iso("2026-04-13T13:35:00-05:00")
    assert plan["return_summary"] == "✈ CLT→MSP • DL 2820"
    assert plan["vacation_name"] == "CLT"


def test_multi_leg_outbound_uses_final_destination_before_homebound_return() -> None:
    now = iso("2026-03-01T08:00:00-06:00")
    events = [
        {
            "summary": "✈ MSP→DTW • DL 2101",
            "description": "Synced by Flighty",
            "start": "2026-03-05T09:10:00-06:00",
            "end": "2026-03-05T11:30:00-05:00",
        },
        {
            "summary": "✈ DTW→AMS • KL 606",
            "description": "Synced by Flighty",
            "start": "2026-03-05T15:45:00-05:00",
            "end": "2026-03-06T06:10:00+01:00",
        },
        {
            "summary": "✈ AMS→INV • KL 921",
            "description": "Synced by Flighty",
            "start": "2026-03-06T09:20:00+01:00",
            "end": "2026-03-06T10:55:00Z",
        },
        {
            "summary": "✈ AMS→MSP • KL 605",
            "description": "Synced by Flighty",
            "start": "2026-03-16T14:15:00+01:00",
            "end": "2026-03-16T17:20:00-05:00",
        },
    ]

    plan = build_vacation_plan(events, now)

    assert plan["decision_code"] == "flight_return"
    assert plan["summary"] == "✈ MSP→DTW • DL 2101"
    assert plan["return_summary"] == "✈ AMS→MSP • KL 605"
    assert plan["vacation_name"] == "INV"
    assert plan["destination_name"] == "INV"


def test_outbound_flight_without_return_uses_lodging_fallback() -> None:
    now = iso("2026-04-01T08:00:00-05:00")
    personal_events = [
        {
            "summary": "✈ MSP→CLT • DL 2819",
            "description": "Synced by Flighty",
            "start": "2026-04-09T14:20:00-05:00",
            "end": "2026-04-09T17:00:00-04:00",
        }
    ]
    work_trip_events = [
        {
            "summary": "Stay at Westin Charlotte",
            "start": "2026-04-09T18:30:00-04:00",
            "end": "2026-04-13T10:00:00-04:00",
            "location": "Charlotte, NC",
        }
    ]

    plan = build_vacation_plan(personal_events, now, work_trip_events=work_trip_events)

    assert plan["reason"] == "flight"
    assert plan["decision_code"] == "flight_lodging"
    assert plan["return_summary"] == ""
    assert plan["fallback_summary"] == "Stay at Westin Charlotte"
    assert plan["fallback_source"] == "lodging span"
    assert plan["end"] == iso("2026-04-13T10:00:00-04:00")


def test_standalone_lodging_trip_without_flights_uses_calendar_window() -> None:
    now = iso("2026-04-01T08:00:00-05:00")
    work_trip_events = [
        {
            "summary": "Stay at AC Hotel Inverness",
            "start": "2026-04-09T18:30:00+01:00",
            "end": "2026-04-13T09:00:00+01:00",
            "location": "Inverness, Scotland",
        }
    ]

    plan = build_vacation_plan([], now, work_trip_events=work_trip_events)

    assert plan["reason"] == "calendar"
    assert plan["decision_code"] == "calendar_lodging"
    assert plan["summary"] == "Stay at AC Hotel Inverness"
    assert plan["fallback_source"] == "lodging span"
    assert plan["vacation_name"] == "Stay at AC Hotel Inverness"


def test_friend_itineraries_to_home_are_ignored() -> None:
    now = iso("2026-03-01T08:00:00-06:00")
    events = [
        {
            "summary": "✈ AMS→MSP • KL 605",
            "description": "Synced by Flighty for Friend arrival",
            "start": "2026-03-16T14:15:00+01:00",
            "end": "2026-03-16T17:20:00-05:00",
        }
    ]

    plan = build_vacation_plan(events, now)

    assert plan["reason"] == "off"
    assert plan["decision_code"] == "off_no_candidate"
    assert "friend itinerary" in plan["ignored_reason"].lower()


def test_home_region_named_flight_does_not_override_curling_trip_block() -> None:
    now = iso("2026-04-11T08:00:00-05:00")
    personal_events = [
        {
            "summary": "Flight to Minnesota (DL 2819)",
            "description": "Created from an email you received in Gmail",
            "start": "2026-04-12T17:47:00-05:00",
            "end": "2026-04-12T20:00:00-05:00",
        }
    ]
    curling_events = [
        {
            "summary": "Arena play down",
            "start": "2026-04-10",
            "end": "2026-04-13",
            "location": "Brookings\nUnited States",
        }
    ]

    plan = build_vacation_plan(personal_events, now, curling_events=curling_events)

    assert plan["reason"] == "calendar"
    assert plan["decision_code"] == "calendar_curling_block"
    assert plan["summary"] == "Arena play down"
    assert plan["outbound_summary"] == ""
    assert plan["fallback_source"] == "curling block"


def test_local_rochester_appointments_do_not_create_trip_window() -> None:
    now = iso("2026-03-01T08:00:00-06:00")
    events = [
        {
            "summary": "Dentist Appointment",
            "location": "Mayo Clinic, Rochester, MN 55905, United States",
            "start": "2026-03-02T10:00:00-06:00",
            "end": "2026-03-02T11:00:00-06:00",
        },
        {
            "summary": "Barber",
            "location": "3001 Hennepin Ave S, Minneapolis, MN 55408, United States",
            "start": "2026-03-03T09:00:00-06:00",
            "end": "2026-03-03T10:00:00-06:00",
        },
    ]

    plan = build_vacation_plan(events, now)

    assert plan["reason"] == "off"
    assert plan["decision_code"] == "off_no_candidate"


@pytest.mark.parametrize(
    ("phrase", "expected_source"),
    [
        ("MSP -> DTW -> AMS -> INV", "multi-leg outbound"),
        ("Friend flights arriving in MSP", "friend homebound"),
        ("Local Rochester appointments", "local false positive"),
        ("Hotel/calendar-only trips", "lodging fallback"),
    ],
)
def test_travel_detection_regression_matrix_documents_priority_cases(
    phrase: str, expected_source: str
) -> None:
    text = MATRIX_PATH.read_text(encoding="utf-8")

    assert "Travel Detection Regression Matrix" in text
    assert "Precedence" in text
    assert phrase in text
    assert expected_source in text
