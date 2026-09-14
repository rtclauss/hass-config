from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "water_usage.yaml"


def _package_text() -> str:
    return PACKAGE_PATH.read_text(encoding="utf-8")


def _automation_block(automation_id: str) -> str:
    text = _package_text()
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_package_tags_new_entities_with_water_usage_package() -> None:
    text = _package_text()

    assert 'package: "water_usage"' in text
    for entity_id in (
        "binary_sensor.dishwasher_and_washer_running",
        "sensor.owner_suite_bathroom_humidity_events_today",
        "sensor.basement_bathroom_humidity_events_today",
        "sensor.guest_bathroom_humidity_events_today",
    ):
        assert f"{entity_id}:" in text


def test_dishwasher_and_washer_template_reuses_existing_binary_sensors() -> None:
    text = _package_text()

    # The whole point is reusing binary_sensor.dishwasher_running and
    # binary_sensor.washing_machine_running from packages/cleaning.yaml -
    # this must not stand up parallel power/vibration sensors of its own.
    assert "name: dishwasher_and_washer_running" in text
    assert "is_state('binary_sensor.dishwasher_running', 'on')" in text
    assert "is_state('binary_sensor.washing_machine_running', 'on')" in text


def test_bathroom_humidity_history_stats_cover_all_three_bathrooms() -> None:
    text = _package_text()

    for source_entity, count_id, time_id in (
        (
            "binary_sensor.bathroom_humidity_high",
            "owner_suite_bathroom_humidity_events_today",
            "owner_suite_bathroom_humid_time_today",
        ),
        (
            "binary_sensor.basement_bathroom_humidity_high",
            "basement_bathroom_humidity_events_today",
            "basement_bathroom_humid_time_today",
        ),
        (
            "binary_sensor.guest_bathroom_humidity_high",
            "guest_bathroom_humidity_events_today",
            "guest_bathroom_humid_time_today",
        ),
    ):
        for unique_id in (count_id, time_id):
            pattern = re.compile(
                rf"platform: history_stats\n\s+name: [^\n]+\n\s+unique_id: {re.escape(unique_id)}\n\s+entity_id: {re.escape(source_entity)}"
            )
            assert pattern.search(text), f"history_stats sensor {unique_id!r} missing or not wired to {source_entity!r}"


def test_leak_automation_requires_sustained_armed_state_and_gates_repeat_alerts() -> None:
    block = _automation_block("water_leak_while_armed")

    assert "entity_id: sensor.water_meter" in block
    assert "entity_id: alarm_control_panel.home_alarm" in block
    assert "armed_away" in block
    assert "armed_night" in block
    # Must require a sustained armed period, not fire on the arming person's
    # own trailing water use.
    assert "minutes: 20" in block
    # Must gate against the configurable threshold, not a hardcoded jitter
    # value that can't be tuned without editing YAML.
    assert "input_number.water_leak_threshold_gallons" in block
    # Must not re-notify every 10-minute reading for the whole armed episode.
    assert "input_boolean.water_leak_alert_sent" in block
    assert "notify.all" in block


def test_leak_alert_reset_clears_flag_on_disarm() -> None:
    block = _automation_block("water_leak_alert_reset")

    assert "entity_id: alarm_control_panel.home_alarm" in block
    assert "to: disarmed" in block
    assert "input_boolean.turn_off" in block
    assert "input_boolean.water_leak_alert_sent" in block
