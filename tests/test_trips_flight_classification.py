from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


CENTRAL = ZoneInfo("America/Chicago")
HOME_CODES = {"MSP", "RST", "MINNEAPOLIS", "MINNEAPOLISSTPAUL", "ROCHESTER"}


@dataclass(frozen=True)
class FlightSignals:
    looks_like_flight: bool
    named_flight: bool
    origin_code: str
    destination_code: str
    destination_name: str


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
    )


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(CENTRAL)


def build_vacation_plan(events: list[dict], now: datetime) -> dict:
    outbound = None
    for event in events:
        start_dt = iso(event["start"])
        signals = parse_flight_signals(
            event.get("summary", ""),
            event.get("description", ""),
            event.get("location", ""),
        )
        is_home_origin = signals.origin_code in {"MSP", "RST"}
        is_home_destination = signals.destination_code in HOME_CODES
        outbound_priority = 0 if is_home_origin else 1 if signals.named_flight else 9

        if (
            signals.looks_like_flight
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
        return {"reason": "off"}

    return_home = None
    for event in events:
        start_dt = iso(event["start"])
        signals = parse_flight_signals(
            event.get("summary", ""),
            event.get("description", ""),
            event.get("location", ""),
        )
        if (
            signals.looks_like_flight
            and signals.destination_code in HOME_CODES
            and start_dt > outbound["start"]
        ):
            candidate = {"summary": event["summary"], "start": start_dt}
            if return_home is None or candidate["start"] < return_home["start"]:
                return_home = candidate

    if return_home is None:
        return {"reason": "off"}

    return {
        "reason": "flight",
        "summary": outbound["summary"],
        "start": outbound["start"],
        "end": return_home["start"] - timedelta(hours=2),
        "return_summary": return_home["summary"],
        "vacation_name": outbound["destination_name"],
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

    assert direct.destination_name == "CLT"
    assert direct.destination_code == "CLT"
    assert verbose.destination_name == "CLT"
    assert verbose.destination_code == "CLT"


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
            "summary": "Tartan Day",
            "start": "2026-04-06T00:00:00-05:00",
            "end": "2026-04-07T00:00:00-05:00",
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
    assert plan["summary"] == "✈ MSP→CLT • DL 2819"
    assert plan["start"] == iso("2026-04-09T14:20:00-05:00")
    assert plan["end"] == iso("2026-04-13T13:35:00-05:00")
    assert plan["return_summary"] == "✈ CLT→MSP • DL 2820"
    assert plan["vacation_name"] == "CLT"
