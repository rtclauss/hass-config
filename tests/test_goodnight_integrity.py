from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"
TV_PATH = ROOT / "packages" / "tv.yaml"


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


def test_goodnight_integrity_script_coordinates_house_shutdown_and_verification() -> None:
    block = _script_block(HOUSE_MODE_PATH, "goodnight_integrity")

    for token in (
        "sleep-safe state",
        "script.house_transition",
        "mode: asleep",
        "script.lights_off_except",
        "switch.office_red_lava_lamp",
        "switch.northern_light_lava_lamp",
        "media_player.lg_webos_smart_tv",
        "media_player.basement",
        "script.turn_off_owner_suite_inovelli_switch_leds",
        "lock.front_door_lock",
        "cover.garage_door",
        "cover.owner_suite_blinds_ha",
        "climate.my_ecobee",
    ):
        assert token in block


def test_goodnight_integrity_respects_guest_mode_and_guest_room_occupancy() -> None:
    block = _script_block(HOUSE_MODE_PATH, "goodnight_integrity")

    for token in (
        "input_boolean.guest_mode",
        "binary_sensor.guest_room_occupancy_2",
        "light.office_all",
        "light.den_all",
        "light.guest_room_ceiling",
        "fan.office_ceiling_fan",
        "fan.guest_room",
        "preset_mode: Guest Sleep",
    ):
        assert token in block


def test_goodnight_integrity_only_notifies_on_verification_exceptions() -> None:
    block = _script_block(HOUSE_MODE_PATH, "goodnight_integrity")

    assert "goodnight_integrity_issues" in block
    assert 'value_template: "{{ goodnight_integrity_issues | trim != \'\' }}"' in block
    assert "notify.all" in block

    for token in (
        "Front door lock is still",
        "Garage door is still",
        "Owner suite blinds are still",
        "Ecobee is unavailable for bedtime verification.",
    ):
        assert token in block


def test_cpap_bedtime_lights_off_still_treats_cpap_as_full_sleep() -> None:
    block = _automation_block(LIGHT_PATH, "cpap_on_lights_off")
    action_block = block.split("    action:", 1)[1]

    assert "sensor.owner_suite_cpap_plug_power" in block
    assert "input_boolean.wakeup_alarm_firing" in block
    assert "light.owner_suite_lamps" in action_block
    assert "light.bed_lightstrip" in action_block
    assert "script.goodnight_integrity" in action_block
    assert "reason: cpap_sleep" in action_block


def test_bed_lamps_off_only_finishes_turning_off_lights() -> None:
    block = _automation_block(LIGHT_PATH, "turn_off_all_lights_when_bed_off")

    assert "sensor.owner_suite_cpap_plug_power" in block
    assert "script.house_transition" in block
    assert "mode: asleep" in block
    assert "script.lights_off_except" in block
    assert "light.outside_front_hue" in block
    assert "light.outside_front_door" in block

    for token in (
        "switch.office_red_lava_lamp",
        "media_player.lg_webos_smart_tv",
        "media_player.basement",
        "script.goodnight_integrity",
    ):
        assert token not in block


def test_in_bed_turn_off_other_lights_marks_house_mode_before_dimming_the_rest_of_the_house() -> None:
    block = _automation_block(LIGHT_PATH, "in_bed_turn_off_other_lights")

    assert "binary_sensor.bayesian_bed_occupancy" in block
    assert "minutes: 10" in block
    assert "script.house_transition" in block
    assert "mode: in_bed" in block
    assert "reason: bed_occupancy_sustained" in block
    assert "script.lights_off_except" in block


def test_basement_lights_auto_on_respects_plex_basement_playback() -> None:
    block = _automation_block(LIGHT_PATH, "basement_lights_auto_on")

    assert "media_player.basement" in block
    assert "media_player.plex_basement_apple_tv" in block
    assert "condition: not" in block
    assert "condition: or" in block
    assert "script.turn_on_basement_lights_sequentially" in block


def test_turn_on_basement_lights_sequentially_stages_path_lights_before_tv_bias() -> None:
    block = _script_block(LIGHT_PATH, "turn_on_basement_lights_sequentially")

    assert "Turn on the basement path in stages" in block
    assert "switch.adaptive_lighting_basement" in block
    assert "for_each:" in block
    assert "{{ repeat.item }}" in block

    ordered_entities = (
        "light.basement_landing_switch",
        "light.basement_great_room_landing_switch_2",
        "light.basement_north_hallway_switch",
        "light.basement_great_room_east_and_middle_switch",
        "light.basement_great_room_west_switch",
        "light.basement_tv_bias",
    )

    positions = [block.index(entity_id) for entity_id in ordered_entities]
    assert positions == sorted(positions)
    assert block.count("seconds: 1") == 1


def test_tv_bed_prep_stops_short_of_full_goodnight_shutdown() -> None:
    block = _automation_block(TV_PATH, "tv_off_at_night_bed_prep")

    assert "scene.bedroom_prep" in block
    assert "script.spotify_bedtime" in block

    for token in (
        "script.goodnight_integrity",
        "cover.garage_door",
        "action: media_player.turn_off",
    ):
        assert token not in block
