from __future__ import annotations

from pathlib import Path


LIGHT_PATH = Path(__file__).resolve().parents[1] / "packages" / "light.yaml"


def _automation_block(automation_id: str) -> str:
    lines = LIGHT_PATH.read_text(encoding="utf-8").splitlines()
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
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_owner_suite_light_auto_on_uses_home_presence_sensor() -> None:
    block = _automation_block("owner_suite_light_auto_on")

    assert "binary_sensor.bayesian_zeke_home" in block
    assert 'state: "on"' in block
    assert "device_tracker.bayesian_zeke_home" not in block
    assert "zone: zone.home" not in block
    assert "light.owner_suite_lamps" in block
    assert "binary_sensor.bayesian_bed_occupancy" in block
    assert "action: switch.turn_on" in block
    assert "switch.adaptive_lighting_owner_suite" in block
    assert "action: script.adaptive_light_turn_on" in block
    assert "adaptive_switch: switch.adaptive_lighting_owner_suite" in block
    assert "transition: 45" in block
    assert "reset_manual_control: true" in block
    assert "\n          brightness_pct:" not in block
    assert "\n          color_temp_kelvin:" not in block


def test_owner_suite_light_auto_on_debounces_bed_clear_before_turning_on() -> None:
    block = _automation_block("owner_suite_light_auto_on")

    assert "entity_id: binary_sensor.bayesian_bed_occupancy" in block
    assert block.count("seconds: 15") == 2
    assert "Bed clear long enough to ignore roll-over/CPAP-removal blips (#852)" in block
    assert "Someone is actually in the room" in block

    bed_clear_trigger = block.split("entity_id: binary_sensor.bayesian_bed_occupancy", maxsplit=1)[1].split(
        "condition:",
        maxsplit=1,
    )[0]
    assert 'from: "on"' in bed_clear_trigger
    assert 'to: "off"' in bed_clear_trigger
    assert "for:\n          seconds: 15" in bed_clear_trigger

    bed_clear_condition = block.split("Bed clear long enough", maxsplit=1)[1].split(
        "Someone is actually in the room",
        maxsplit=1,
    )[0]
    assert 'state: "off"' in bed_clear_condition
    assert "for:\n            seconds: 15" in bed_clear_condition

    room_presence_condition = block.split("Someone is actually in the room", maxsplit=1)[1].split(
        "action:",
        maxsplit=1,
    )[0]
    assert "condition: or" in room_presence_condition
    assert "entity_id: binary_sensor.presense" in room_presence_condition
    assert "entity_id: binary_sensor.bedroom_occupancy" in room_presence_condition


def test_owner_suite_light_auto_off_combines_latch_and_morning_paths() -> None:
    package = LIGHT_PATH.read_text(encoding="utf-8")
    block = _automation_block("owner_suite_light_auto_off")

    assert "owner_suite_light_auto_off_in_morning" not in package
    assert "binary_sensor.bedroom_occupancy" in block
    assert "binary_sensor.bayesian_bed_occupancy" in block
    assert "condition: or" in block
    assert "input_boolean.owner_suite_bedroom_auto_on" in block
    assert 'after: "00:06:00"' in block
    assert 'before: "12:00:00"' in block
    assert "action: light.turn_off" in block
    assert "light.owner_suite_lamps" in block
    assert "fan.owner_suite" in block
    assert "action: input_boolean.turn_off" in block


def test_upstairs_hallway_motion_uses_hallway_adaptive_lighting_switch() -> None:
    block = _automation_block("toggle_hallway_day")

    upstairs_branch = block.split("condition: trigger\n                id: upstairs-motion-sensed", maxsplit=1)[1].split(
        "id: upstairs-motion-not-detected",
        maxsplit=1,
    )[0]

    assert "light.hall_upstairs_switch" in upstairs_branch
    assert "light.hall_stairway" in upstairs_branch
    assert "adaptive_switch: switch.adaptive_lighting_hallway" in upstairs_branch
    assert "entity_id: switch.adaptive_lighting_owner_suite" not in upstairs_branch
