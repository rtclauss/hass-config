from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"


def _script_block(script_id: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line == f"  {script_id}:":
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script {script_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break

    return "\n".join(lines[start:end])


def _automation_block(automation_id: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line == f"  - id: {automation_id}":
            start = index
            break

        if line != f"    id: {automation_id}":
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_trip_mode_sync_automation_suspends_and_restores_inovelli_leds() -> None:
    block = _automation_block("sync_trip_mode_inovelli_leds")

    assert "event: start" in block
    assert "entity_id: input_boolean.trip" in block
    assert 'to: "on"' in block
    assert 'to: "off"' in block
    assert "script.turn_off_all_inovelli_switch_leds" in block
    assert "script.restore_inovelli_switch_leds_from_trip" in block


def test_trip_suspend_script_zeros_led_intensities_and_clears_active_effects() -> None:
    block = _script_block("turn_off_all_inovelli_switch_leds")

    assert "all_switches_led_intensity_on" in block
    assert "all_switches_led_intensity_off" in block
    assert "value: 0" in block
    assert "'clear_effect'" in block
    assert "zigbee2mqtt/{{ repeat.item }}/set" in block


def test_trip_restore_script_reuses_existing_day_and_night_profiles() -> None:
    block = _script_block("restore_inovelli_switch_leds_from_trip")

    for token in (
        "entity_id: switch.sleep_mode",
        "entity_id: sun.sun",
        "state: \"below_horizon\"",
        "script.night_tv_mode_switches",
        "script.day_mode_switches_general",
        "script.day_mode_switches_office_guest_room",
        "script.day_mode_switches_owner_suite_bedroom",
        "is_state('input_boolean.guest_mode', 'off')",
        "today_at('12:00')",
        "binary_sensor.bayesian_bed_occupancy",
        "binary_sensor.owner_suite_bathroom_room_occupancy",
        "binary_sensor.hall_upstairs_motion_occupancy",
        "today_at('08:00')",
    ):
        assert token in block


def test_trip_mode_blocks_day_and_night_led_scripts_from_relighting_switches() -> None:
    for script_id in (
        "night_tv_mode_switches",
        "day_mode_switches",
        "day_mode_switches_general",
        "day_mode_switches_owner_suite_bedroom",
        "day_mode_switches_office_guest_room",
    ):
        block = _script_block(script_id)

        assert (
            re.search(
                r"entity_id: input_boolean\.trip\n\s+state: \"off\"",
                block,
            )
            or "*trip_led_updates_allowed" in block
        ), f"{script_id} should stop when trip mode is active"
