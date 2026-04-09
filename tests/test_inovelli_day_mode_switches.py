from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"


def _script_block(path: Path, script_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r} in {path.name}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_day_mode_wrapper_runs_general_bedroom_and_office_guest_scripts() -> None:
    block = _script_block(ZIGBEE_ZWAVE_PATH, "day_mode_switches")

    for script_entity in (
        "script.day_mode_switches_general",
        "script.day_mode_switches_owner_suite_bedroom",
        "script.day_mode_switches_office_guest_room",
    ):
        assert script_entity in block


def test_general_day_mode_script_excludes_delayed_owner_suite_office_and_guest_switches() -> None:
    block = _script_block(ZIGBEE_ZWAVE_PATH, "day_mode_switches_general")

    for delayed_switch in (
        "owner_suite_fan_switch",
        "office_fan_switch",
        "guest_room_fan_switch",
    ):
        assert f"rejectattr('entity_id', 'search', '{delayed_switch}')" in block

    for token in (
        "all_day_mode_singletapbehavior_switches",
        "all_day_mode_defaultlevellocal_switches",
        "all_day_mode_defaultlevelremote_switches",
        'message: "Setting light switch day mode colors and full-brightness defaults"',
    ):
        assert token in block


def test_turn_off_sleep_mode_uses_general_day_mode_and_early_office_guest_when_no_guests() -> None:
    block = _automation_block(LIGHT_PATH, "turn_off_sleep_mode")

    assert 'at: "08:00:00"' in block
    assert "script.day_mode_switches_general" in block
    assert "entity_id: input_boolean.guest_mode" in block
    assert 'state: "off"' in block
    assert "script.day_mode_switches_office_guest_room" in block
    assert "script.day_mode_switches\n" not in block


def test_guest_mode_keeps_office_and_guest_room_switches_delayed_until_noon() -> None:
    block = _automation_block(LIGHT_PATH, "enable_office_guest_room_switch_day_mode_for_guest_mode")

    assert 'at: "12:00:00"' in block
    assert "entity_id: input_boolean.guest_mode" in block
    assert 'state: "on"' in block
    assert "script.day_mode_switches_office_guest_room" in block


def test_owner_suite_bedroom_day_mode_waits_for_bed_bathroom_and_hallway_activity() -> None:
    block = _automation_block(LIGHT_PATH, "enable_owner_suite_bedroom_switch_day_mode_after_morning_activity")

    for entity_id in (
        "binary_sensor.bayesian_bed_occupancy",
        "binary_sensor.owner_suite_bathroom_room_occupancy",
        "binary_sensor.hall_upstairs_motion_occupancy",
    ):
        assert entity_id in block

    assert 'after: "07:59:59"' in block
    assert 'before: "12:00:00"' in block
    assert "today_at('08:00')" in block
    assert "script.day_mode_switches_owner_suite_bedroom" in block


def test_owner_suite_night_mode_script_sets_suite_led_bars_to_red() -> None:
    block = _script_block(ZIGBEE_ZWAVE_PATH, "night_mode_switches_owner_suite")

    for entity_id in (
        "number.owner_suite_closet_ledcolorwhenoff",
        "number.owner_suite_fan_switch_ledcolorwhenoff",
        "number.owner_suite_bathroom_vanity_ledcolorwhenoff",
        "number.owner_suite_closet_ledintensitywhenoff",
        "number.owner_suite_fan_switch_ledintensitywhenoff",
        "number.owner_suite_bathroom_vanity_ledintensitywhenoff",
        "number.owner_suite_closet_ledintensitywhenon",
        "number.owner_suite_fan_switch_ledintensitywhenon",
        "number.owner_suite_bathroom_vanity_ledintensitywhenon",
        "number.owner_suite_closet_ledcolorwhenon",
        "number.owner_suite_fan_switch_ledcolorwhenon",
        "number.owner_suite_bathroom_vanity_ledcolorwhenon",
    ):
        assert entity_id in block

    assert 'value: "0"' in block
    assert 'value: "1"' in block
    assert 'value: "50"' in block
    assert "Setting owner suite switch LED colors to nighttime red" in block


def test_owner_suite_switch_leds_return_to_night_red_when_lamps_turn_on_overnight() -> None:
    block = _automation_block(LIGHT_PATH, "owner_suite_switch_leds_red_when_lamps_on_at_night")

    assert "entity_id: light.owner_suite_lamps" in block
    assert 'to: "on"' in block
    assert 'after: "22:00:00"' in block
    assert 'before: "06:00:00"' in block
    assert "script.night_mode_switches_owner_suite" in block


def test_owner_suite_night_lamp_shutdown_turns_off_switch_leds_with_bed_strip() -> None:
    block = _automation_block(LIGHT_PATH, "owner_suite_bed_strip_off_when_lamps_off")

    assert "entity_id: light.owner_suite_lamps" in block
    assert 'to: "off"' in block
    assert "entity_id: light.bed_lightstrip" in block
    assert 'after: "22:00:00"' in block
    assert 'before: "06:00:00"' in block
    assert "script.turn_off_owner_suite_inovelli_switch_leds" in block


def test_wake_up_script_no_longer_forces_day_mode_before_eight_am() -> None:
    block = _script_block(WORKDAY_PATH, "wake_up_script")

    assert "switch.sleep_mode" in block
    assert "script.day_mode_switches" not in block
