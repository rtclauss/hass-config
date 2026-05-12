from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "inky_displays.yaml"
DOC_PATH = ROOT / "docs" / "inky_displays.md"
QUOTE_PATH = ROOT / "data" / "inky_owner_suite_quotes.yaml"


def _package_text() -> str:
    return PACKAGE_PATH.read_text(encoding="utf-8")


def _script_block(script_id: str) -> str:
    lines = _package_text().splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break

    return "\n".join(lines[start:end])


def _automation_block(automation_id: str) -> str:
    lines = _package_text().splitlines()
    start = None

    for index, line in enumerate(lines):
        if line == f"  - id: {automation_id}":
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find automation id {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - id: "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_owner_suite_publish_script_uses_documented_mqtt_contract() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "action: mqtt.publish" in block
    assert "topic: home/inky/owner_suite/state" in block
    assert "retain: true" in block
    assert "'schema_version': 1" in block
    assert "'display_id': 'owner_suite'" in block
    assert "'accent': 'red'" in block
    assert "| tojson" in block


def test_owner_suite_payload_includes_modes_and_four_rows() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    for mode in ("night_preview", "morning", "up_for_day", "midday"):
        assert mode in block

    for label in (
        "Weather",
        "Tomorrow",
        "Alarm",
        "Meeting",
        "Status",
        "Flight",
        "Airport",
        "Dest Wx",
        "Next",
        "Place",
        "Quote",
    ):
        assert f"'label': '{label}'" in block


def test_owner_suite_footer_uses_publish_time_in_24_hour_format() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "'footer': 'Updated ' ~ now().strftime('%H:%M')" in block
    assert "%I:%M" not in block
    assert "%p" not in block
    assert "sensor.time" not in block


def test_owner_suite_morning_mode_is_limited_to_pre_noon_wake_firing() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "is_state('input_boolean.wakeup_alarm_firing', 'on') and now().hour < 12" in block
    assert "{% elif now().hour >= 12 %}" in block


def test_owner_suite_evening_auto_mode_uses_night_preview() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "{% elif now().hour >= 20 %}" in block
    assert block.index("{% elif now().hour >= 20 %}") < block.index("{% elif now().hour >= 12 %}")


def test_owner_suite_night_preview_includes_current_and_tomorrow_weather() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "action: weather.get_forecasts" in block
    assert "owner_suite_daily_forecast: {}" in block
    assert "owner_suite_hourly_forecast: {}" in block
    assert "condition: not" in block
    assert "entity_id: weather.tomorrow_io_the_brewery_daily" in block
    assert '  - "unknown"' in block
    assert '  - "unavailable"' in block
    assert "type: daily" in block
    assert "response_variable: owner_suite_daily_forecast" in block
    assert "type: hourly" in block
    assert "response_variable: owner_suite_hourly_forecast" in block
    assert "daily_forecast_rows = daily_response.get(weather_entity" in block
    assert "forecast_rows = hourly_response.get(weather_entity" in block
    assert "forecast_rows = (state_attr('sensor.active_weather_entity_id', 'forecast_json')" in block
    assert "tomorrow_start_ts = as_timestamp(today_at('00:00') + timedelta(days=1))" in block
    assert "forecast.temperature | int(default=none)" in block
    assert "resolved_mode == 'night_preview'" in block
    assert "'label': 'Tomorrow'" in block
    assert "'value': tomorrow.value" in block
    night_block = block[block.index("resolved_mode == 'night_preview'") : block.index("{% elif flight_active")]
    assert "night_detail_row" in night_block
    assert "'label': 'Alarm'" in night_block
    assert "'label': 'Meeting'" in night_block


def test_owner_suite_daytime_rows_use_calendar_or_quote_context_not_alarms() -> None:
    block = _script_block("publish_owner_suite_inky_display")
    daytime_block = block[block.index("{% else %}\n              {% if next_calendar.has_event %}") : block.index("            {% endif %}\n            {{ {")]
    quote_block = daytime_block[daytime_block.index("{% else %}") :]

    assert "action: calendar.get_events" in block
    assert "response_variable: owner_suite_calendar_window" in block
    assert "calendar_response.get('events'" in block
    assert "item.location" in block
    assert "'label': 'Next'" in daytime_block
    assert "'value': next_calendar.time" in daytime_block
    assert "'label': 'Place'" in daytime_block
    assert "'value': next_calendar.place" in daytime_block
    assert "'label': 'Quote'" in daytime_block
    assert "'value': quote_value" in daytime_block
    assert "'label': 'Speaker'" in quote_block
    assert "'value': quote_speaker" in quote_block
    assert "'label': 'Source'" not in quote_block
    assert "Sci-fi/fantasy" not in quote_block
    assert "'label': 'Alarm'" not in daytime_block
    assert "'label': 'Meeting'" not in daytime_block


def test_owner_suite_quote_entries_load_from_curated_file() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "quote_entries: !include ../data/inky_owner_suite_quotes.yaml" in block
    assert "{% set quote_entries = [" not in block


def test_owner_suite_quote_file_stays_screen_safe() -> None:
    text = QUOTE_PATH.read_text(encoding="utf-8")
    quotes = re.findall(r"^-\s+quote:\s+(.+)$", text, flags=re.MULTILINE)
    speakers = re.findall(r"^\s+speaker:\s+(.+)$", text, flags=re.MULTILINE)

    assert len(quotes) >= 10
    assert len(quotes) == len(speakers)

    for quote in quotes:
        clean_quote = quote.strip("\"'")
        assert len(clean_quote) <= 34

    for speaker in speakers:
        clean_speaker = speaker.strip("\"'")
        assert len(clean_speaker) <= 24

    for required_speaker in (
        "Han Solo",
        "Jean-Luc Picard",
        "The Culture",
        "Jernau Gurgeh",
        "Carl",
        "Princess Donut",
        "The Guide",
        "The Librarian",
        "Brutha",
    ):
        assert f"speaker: {required_speaker}" in text


def test_owner_suite_payload_maps_weather_icons_and_exceptions() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    for icon in (
        "mdi:weather-sunny",
        "mdi:weather-partly-cloudy",
        "mdi:weather-cloudy",
        "mdi:weather-rainy",
        "mdi:weather-snowy",
        "mdi:weather-lightning",
    ):
        assert icon in block

    assert "sensor.nws_dakota_county_alerts_alerts_are_active" in block
    assert "cover.garage_door" in block
    assert "binary_sensor.main_foyer_front_door_contact" in block
    assert "input_boolean.trip" in block
    assert "binary_sensor.planned_vacation_calendar" in block


def test_owner_suite_payload_warns_about_near_term_and_event_precipitation() -> None:
    block = _script_block("publish_owner_suite_inky_display")
    automation = _automation_block("publish_owner_suite_inky_display")

    for entity_id in ("sensor.precip_next_1hr", "calendar.ryan_claussen"):
        assert entity_id in block
        assert entity_id in automation

    assert "precip_next_hour >= 40" in block
    assert "'Rain soon ' ~ precip_next_hour ~ '%'" in block
    assert "state_attr('calendar.ryan_claussen', 'start_time')" in block
    assert "state_attr('calendar.ryan_claussen', 'end_time')" in block
    assert "as_timestamp(event_start, default=none)" in block
    assert "as_timestamp(forecast.datetime, default=none)" in block
    assert "forecast_ts >= event_start_ts" in block
    assert "event_start_dt" not in block
    assert "event.max_precip >= 40" in block
    assert "forecast.condition | default('', true) in precip_conditions" in block
    assert "'Wx for ' ~ event_title" in block


def test_owner_suite_payload_consumes_flight_status_sources() -> None:
    block = _script_block("publish_owner_suite_inky_display")
    automation = _automation_block("publish_owner_suite_inky_display")

    for entity_id in (
        "sensor.next_travel_flight",
        "sensor.next_travel_flight_live_status",
        "sensor.next_travel_flight_airport_delay",
        "sensor.next_travel_flight_destination_weather",
    ):
        assert entity_id in block
        assert entity_id in automation

    assert "travel_rows" in block
    assert "exception_active = weather_alert or garage_open or front_door_open or rain_next_hour or event_weather" in block
    assert "resolved_mode in ['morning', 'up_for_day', 'midday']" in block


def test_owner_suite_automation_coalesces_meaningful_refresh_events() -> None:
    block = _automation_block("publish_owner_suite_inky_display")

    assert "mode: restart" in block
    assert "seconds: 15" in block
    assert "trigger: time" in block
    assert 'at: "12:00:00"' in block
    assert "trigger: homeassistant" in block
    assert "action: script.publish_owner_suite_inky_display" in block
    assert "sensor.time" not in block


def test_owner_suite_automation_skips_publish_when_house_is_unoccupied() -> None:
    block = _automation_block("publish_owner_suite_inky_display")

    assert "input_boolean.guest_mode" in block
    assert "binary_sensor.bayesian_zeke_home" in block
    assert "alias: Publish only when Ryan is home or guest mode is active" in block
    assert "is_state('input_boolean.guest_mode', 'on')" in block
    assert "is_state('binary_sensor.bayesian_zeke_home', 'on')" in block
    assert "is_state('input_boolean.trip', 'off')" in block


def test_owner_suite_publish_script_enforces_occupancy_guard() -> None:
    block = _script_block("publish_owner_suite_inky_display")

    assert "alias: Publish only when Ryan is home or guest mode is active" in block
    assert "is_state('input_boolean.guest_mode', 'on')" in block
    assert "is_state('binary_sensor.bayesian_zeke_home', 'on')" in block
    assert "is_state('input_boolean.trip', 'off')" in block
    assert block.index("alias: Publish only when Ryan is home") < block.index("action: mqtt.publish")


def test_owner_suite_sources_are_documented() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "script.publish_owner_suite_inky_display" in text
    assert "automation.publish_owner_suite_inky_display" in text
    assert "home/inky/owner_suite/state" in text
    assert "Updated 21:42" in text
    assert "publish script only allows updates when guest mode is active" in text
    assert "Ryan returning home" in text
    assert "rain in the next hour" in text
    assert "precipitation/weather during the next `calendar.ryan_claussen` event" in text
