from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"
MEDIA_PLAYER_PATH = ROOT / "packages" / "media_player.yaml"
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
    id_lines = {f"    id: {automation_id}", f"  - id: {automation_id}"}
    start = None

    for index, line in enumerate(lines):
        if line not in id_lines:
            continue

        if line.startswith("  - "):
            start = index
        else:
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


def test_day_mode_wrapper_runs_general_office_guest_and_owner_suite_policy_scripts() -> None:
    block = _script_block(ZIGBEE_ZWAVE_PATH, "day_mode_switches")

    for script_entity in (
        "script.day_mode_switches_general",
        "script.day_mode_switches_office_guest_room",
        "script.apply_owner_suite_inovelli_led_policy",
    ):
        assert script_entity in block

    assert "policy: day" in block


def test_general_day_mode_script_excludes_delayed_owner_suite_office_and_guest_switches() -> None:
    block = _script_block(ZIGBEE_ZWAVE_PATH, "day_mode_switches_general")

    for delayed_switch in (
        "owner_suite_fan_switch",
        "owner_suite_bathroom_vanity",
        "owner_suite_closet",
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


def test_turn_off_sleep_mode_uses_workday_owner_suite_bathroom_policy_and_early_office_guest_when_no_guests() -> None:
    block = _automation_block(LIGHT_PATH, "turn_off_sleep_mode")

    assert 'at: "08:00:00"' in block
    assert "script.day_mode_switches_general" in block
    assert "binary_sensor.workday_sensor" in block
    assert "script.apply_owner_suite_inovelli_led_policy" in block
    assert "policy: day" in block
    assert "scope: bathroom" in block
    assert "entity_id: input_boolean.guest_mode" in block
    assert 'state: "off"' in block
    assert "script.day_mode_switches_office_guest_room" in block
    assert "script.day_mode_switches_owner_suite_bathroom" not in block
    assert "script.day_mode_switches\n" not in block


def test_turn_off_sleep_mode_owner_suite_bathroom_is_workday_sensor_gated() -> None:
    block = _automation_block(LIGHT_PATH, "turn_off_sleep_mode")

    bathroom_idx = block.index("script.apply_owner_suite_inovelli_led_policy")
    workday_idx = block.index("binary_sensor.workday_sensor")
    assert workday_idx < bathroom_idx


def test_guest_mode_keeps_office_and_guest_room_switches_delayed_until_noon() -> None:
    block = _automation_block(LIGHT_PATH, "enable_office_guest_room_switch_day_mode_for_guest_mode")

    assert 'at: "12:00:00"' in block
    assert "entity_id: input_boolean.guest_mode" in block
    assert 'state: "on"' in block
    assert "script.day_mode_switches_office_guest_room" in block


def test_owner_suite_bedroom_day_mode_waits_for_bed_bathroom_and_hallway_activity() -> None:
    block = _automation_block(LIGHT_PATH, "enable_owner_suite_bedroom_switch_day_mode_after_morning_activity")

    for entity_id in (
        "binary_sensor.workday_sensor",
        "binary_sensor.bayesian_bed_occupancy",
        "binary_sensor.owner_suite_bathroom_room_occupancy",
        "binary_sensor.bedroom_occupancy",
    ):
        assert entity_id in block

    assert 'after: "07:59:59"' in block
    assert "today_at('08:00')" in block
    assert "script.apply_owner_suite_inovelli_led_policy" in block
    assert "policy: day" in block
    assert "scope: bedroom" in block
    assert "script.owner_suite_morning_transition" not in block


def test_owner_suite_bedroom_day_mode_is_workday_sensor_gated() -> None:
    block = _automation_block(LIGHT_PATH, "enable_owner_suite_bedroom_switch_day_mode_after_morning_activity")

    assert "binary_sensor.workday_sensor" in block
    assert "weekday:" not in block


def test_owner_suite_bathroom_day_mode_script_targets_bathroom_and_closet_leds() -> None:
    wrapper = _script_block(ZIGBEE_ZWAVE_PATH, "day_mode_switches_owner_suite_bathroom")
    block = _script_block(ZIGBEE_ZWAVE_PATH, "day_mode_switches_owner_suite_scope")

    assert "script.day_mode_switches_owner_suite_scope" in wrapper
    assert "scope: bathroom" in wrapper
    assert "requested_scope: \"{{ scope | default('bedroom') }}\"" in block
    assert "owner_suite_bathroom_vanity|owner_suite_closet" in block
    assert "owner_suite_fan_switch" in block
    assert "Setting owner suite bathroom and closet switch day mode colors" in block
    assert "Setting owner suite bedroom switch day mode colors" in block
    assert 'value: "170"' in block
    assert 'value: "75"' in block
    assert 'value: "1"' in block


def test_owner_suite_led_policy_dispatches_day_night_red_and_dark_modes() -> None:
    block = _script_block(ZIGBEE_ZWAVE_PATH, "apply_owner_suite_inovelli_led_policy")

    for token in (
        "requested_policy",
        "requested_scope",
        "requested_policy == 'day'",
        "requested_scope in ['all', 'bedroom']",
        "requested_scope in ['all', 'bathroom']",
        "script.day_mode_switches_owner_suite_bedroom",
        "script.day_mode_switches_owner_suite_bathroom",
        "requested_policy == 'night_red'",
        "script.night_mode_switches_owner_suite",
        "requested_policy == 'dark'",
        "script.turn_off_owner_suite_inovelli_switch_leds",
    ):
        assert token in block


def test_wake_up_script_no_longer_forces_day_mode_before_eight_am() -> None:
    block = _script_block(WORKDAY_PATH, "wake_up_script")

    assert "script.owner_suite_morning_transition" in block
    assert "script.day_mode_switches" not in block


def test_play_music_in_bathroom_led_action_is_workday_sensor_gated() -> None:
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    policy_idx = block.index("script.apply_owner_suite_inovelli_led_policy")
    workday_idx = block.index("binary_sensor.workday_sensor")
    assert workday_idx < policy_idx
    assert "policy: day" in block
    assert "scope: bathroom" in block
    assert "script.day_mode_switches_office_guest_room" in block
    assert "number.owner_suite_closet_ledintensitywhenoff" not in block


def test_owner_suite_switch_leds_return_to_night_red_when_lamps_turn_on_overnight() -> None:
    block = _automation_block(LIGHT_PATH, "owner_suite_switch_leds_red_when_lamps_on_at_night")

    assert "entity_id: light.owner_suite_lamps" in block
    assert 'to: "on"' in block
    assert 'after: "22:00:00"' in block
    assert 'before: "06:00:00"' in block
    assert "script.apply_owner_suite_inovelli_led_policy" in block
    assert "policy: night_red" in block


def test_owner_suite_night_lamp_shutdown_turns_off_switch_leds_with_bed_strip() -> None:
    block = _automation_block(LIGHT_PATH, "owner_suite_bed_strip_off_when_lamps_off")

    assert "entity_id: light.owner_suite_lamps" in block
    assert 'to: "off"' in block
    assert "entity_id: light.bed_lightstrip" in block
    assert 'after: "22:00:00"' in block
    assert 'before: "06:00:00"' in block
    assert "script.apply_owner_suite_inovelli_led_policy" in block
    assert "policy: dark" in block
