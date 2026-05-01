from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "flight_status.yaml"


def _package_text() -> str:
    return PACKAGE_PATH.read_text(encoding="utf-8")


def test_flight_status_package_uses_calendar_and_rest_sources() -> None:
    text = _package_text()

    assert "calendar.get_events" in text
    assert "calendar.ryan_claussen" in text
    assert "calendar.work_trip" in text
    assert "rest_command:" in text
    assert "flightaware_next_travel_flight:" in text
    assert "https://aeroapi.flightaware.com/aeroapi/flights/" in text
    assert "!secret flightaware_aeroapi_key" in text
    assert "!secret tsawaittimes_msp_airport_url" in text
    assert "!secret tsawaittimes_rst_airport_url" in text
    assert "https://api.open-meteo.com/v1/forecast" in text


def test_flight_status_package_exposes_normalized_display_sensors() -> None:
    text = _package_text()

    for entity_name in (
        "Next Travel Flight",
        "Next Travel Flight Live Status",
        "Next Travel Flight TSA Wait",
        "Next Travel Flight Airport Delay",
        "Next Travel Flight Destination Weather",
    ):
        assert f"name: {entity_name}" in text

    for attribute in (
        "origin_code",
        "destination_code",
        "destination_latitude",
        "destination_longitude",
        "departure_delay_minutes",
        "predicted_takeoff",
        "arrival_delay_minutes",
    ):
        assert attribute in text


def test_flight_status_keeps_calendar_fallback_when_live_api_is_unavailable() -> None:
    text = _package_text()

    assert "scheduled" in text
    assert "state_attr('sensor.next_travel_flight', 'start_time')" in text
    assert "state_attr('sensor.next_travel_flight', 'end_time')" in text
    assert "state_attr('sensor.next_travel_flight', 'ident')" in text
    assert "calendar" in text
    assert "active_window" in text


def test_flightaware_polling_policy_avoids_unnecessary_calls() -> None:
    text = _package_text()

    assert "flights/none" not in text
    assert "scan_interval: 600" not in text
    assert "should_poll_flightaware" in text
    assert "has_ident" in text
    assert "within_3_days" in text
    assert "hourly_slot" in text
    assert "within_24h_until_takeoff" in text
    assert "has_taken_off" in text
    assert "stopped_after_takeoff" in text
    assert "every_15_minutes_until_takeoff" in text
    assert "hourly_within_3_days" in text


def test_route_style_flighty_events_win_over_gmail_duplicates() -> None:
    text = _package_text()

    assert "'CMH': {'name': 'Columbus'" in text
    assert "'PIT': {'name': 'Pittsburgh'" in text
    assert "'ATL': {'name': 'Atlanta'" in text
    assert "'SFO': {'name': 'San Francisco'" in text
    assert "source_priority = 0 if route_summary else 1 if ident_ns.value != '' else 2" in text
    assert "source_priority < ns.match.source_priority" in text
    assert "' ' not in destination_name and route_destination_code | length == 3" in text
    assert "destination_name.split('(', 1)[1].split(')', 1)[0]" in text


def test_june_calendar_formats_are_supported() -> None:
    text = _package_text()

    # June trip samples rely on Flighty route events for airport codes; Gmail
    # duplicates can still contribute the flight ident and schedule as fallback.
    assert "destination_alias_map" not in text
    assert "'PIT': {'name': 'Pittsburgh'" in text
    assert "route_destination_code = destination_name | regex_replace('[^A-Za-z]', '') | upper" in text
