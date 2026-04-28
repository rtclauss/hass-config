from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "inky_displays.yaml"
DOC_PATH = ROOT / "docs" / "inky_displays.md"


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

    for label in ("Weather", "Alarm", "Meeting", "Status"):
        assert f"'label': '{label}'" in block


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


def test_owner_suite_automation_coalesces_meaningful_refresh_events() -> None:
    block = _automation_block("publish_owner_suite_inky_display")

    assert "mode: restart" in block
    assert "seconds: 15" in block
    assert "trigger: time" in block
    assert 'at: "12:00:00"' in block
    assert "trigger: homeassistant" in block
    assert "action: script.publish_owner_suite_inky_display" in block
    assert "sensor.time" not in block


def test_owner_suite_sources_are_documented() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "script.publish_owner_suite_inky_display" in text
    assert "automation.publish_owner_suite_inky_display" in text
    assert "home/inky/owner_suite/state" in text
