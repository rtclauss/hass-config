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
        "input_number.water_meter_reading_at_arm",
    ):
        assert f"{entity_id}:" in text


def test_guest_bathroom_has_no_usage_tracking_per_room_intent_privacy_policy() -> None:
    # docs/room_intent.yaml marks the guest bathroom always guest-private and
    # lists humidity-driven exhaust control as its only sanctioned automation
    # use - not persistent count/duration usage analytics, which is exactly
    # the kind of "managed item" the guest_privacy_first policy says must not
    # intrude on guest privacy. This package must not stand up guest-bathroom
    # equivalents of the owner-suite/basement humidity-event sensors.
    text = _package_text()

    assert "guest_bathroom" not in text


def test_dishwasher_and_washer_template_reuses_existing_binary_sensors() -> None:
    text = _package_text()

    # The whole point is reusing binary_sensor.dishwasher_running and
    # binary_sensor.washing_machine_running from packages/cleaning.yaml -
    # this must not stand up parallel power/vibration sensors of its own.
    assert "name: dishwasher_and_washer_running" in text
    assert "is_state('binary_sensor.dishwasher_running', 'on')" in text
    assert "is_state('binary_sensor.washing_machine_running', 'on')" in text


def test_bathroom_humidity_history_stats_cover_owner_suite_and_basement_only() -> None:
    # Deliberately not the guest bathroom - see
    # test_guest_bathroom_has_no_usage_tracking_per_room_intent_privacy_policy.
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


def test_leak_check_compares_against_arm_time_baseline_not_the_previous_poll() -> None:
    # Regression test: comparing only trigger.from_state vs trigger.to_state
    # misses a slow leak that adds less than the threshold on every single
    # 10-minute poll (e.g. 0.9 gal/poll against a 1 gal threshold - never
    # trips, despite 40+ gal overnight). The fix compares against a baseline
    # captured once per armed episode instead.
    block = _automation_block("water_leak_while_armed")

    assert "input_number.water_meter_reading_at_arm" in block
    assert "trigger.from_state.state | float" not in block


def test_arm_baseline_automation_captures_the_reading_when_armed() -> None:
    block = _automation_block("water_meter_capture_arm_baseline")

    assert "entity_id: alarm_control_panel.home_alarm" in block
    assert "armed_away" in block
    assert "armed_night" in block
    assert "input_number.set_value" in block
    assert "input_number.water_meter_reading_at_arm" in block
    assert "states('sensor.water_meter')" in block
    # This automation must NOT also handle the restart case - see
    # test_restart_backfill_only_fires_when_no_baseline_was_ever_captured for
    # why unconditionally recapturing on every restart is wrong.
    assert "event: start" not in block


def test_restart_backfill_only_fires_when_no_baseline_was_ever_captured() -> None:
    # Regression test: input_number restores its own value across a normal
    # HA restart, so unconditionally recapturing the baseline on every
    # restart while armed would erase legitimate accumulated leak progress
    # from before the restart (by resetting the baseline to the
    # already-risen current reading). This must only backfill when no
    # baseline exists yet for the current armed episode.
    block = _automation_block("water_meter_backfill_arm_baseline_on_restart")

    assert "event: start" in block
    assert "entity_id: alarm_control_panel.home_alarm" in block
    assert "armed_away" in block
    assert "armed_night" in block
    assert "input_number.water_meter_reading_at_arm" in block
    assert "input_number.set_value" in block


def test_leak_alert_reset_clears_flag_on_disarm() -> None:
    block = _automation_block("water_leak_alert_reset")

    assert "entity_id: alarm_control_panel.home_alarm" in block
    assert "to: disarmed" in block
    assert "input_boolean.turn_off" in block
    assert "input_boolean.water_leak_alert_sent" in block
