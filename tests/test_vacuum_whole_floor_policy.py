from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
CURLING_PATH = ROOT / "packages" / "curling.yaml"


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


def _script_block(path: Path, script_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    target = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == target:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script block {script_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            end = index
            break

    return "\n".join(lines[start:end])


def test_whole_floor_helper_starts_both_levels() -> None:
    helper_block = _script_block(VACUUM_PATH, "vacuum_main_and_upstairs_levels")
    main_level_block = _script_block(VACUUM_PATH, "vacuum_main_level_full_floor")
    policy_block = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    vacuum_only_block = _script_block(VACUUM_PATH, "x40_ultra_main_level_vacuum_only")
    mop_after_vacuum_block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")
    upstairs_block = _script_block(VACUUM_PATH, "vacuum_upstairs_full_floor")

    assert "action: script.vacuum_main_level_full_floor" in helper_block
    assert "action: script.vacuum_upstairs_full_floor" in helper_block
    assert "force_mop:" in helper_block
    assert "MapSegmentationCapability/clean/set" not in helper_block
    assert '"iterations": 4' not in helper_block

    assert "action: script.x40_ultra_main_level_policy_clean" in main_level_block
    assert "entity_id: vacuum.x40_ultra" in vacuum_only_block
    assert "action: dreame_vacuum.vacuum_set_custom_cleaning" in vacuum_only_block
    assert "action: dreame_vacuum.vacuum_clean_segment" in vacuum_only_block
    assert "segments: [4, 3, 1, 2, 6, 5]" in vacuum_only_block
    assert "cleaning_mode: [0, 0, 0, 0, 0, 0]" in vacuum_only_block
    assert "action: script.x40_ultra_main_level_mop_after_vacuum" in policy_block
    assert "action: script.x40_ultra_main_level_vacuum_only" in policy_block
    assert "cleaning_mode: [1, 1, 1, 1, 1, 1]" in mop_after_vacuum_block
    assert "input_boolean.x40_ultra_mop_pass_pending" in mop_after_vacuum_block
    assert "input_datetime.x40_ultra_last_mopped_at" in mop_after_vacuum_block
    assert "valetudo/upstairs-vacuum/BasicControlCapability/operation/set" in upstairs_block
    assert "payload: START" in upstairs_block


def test_upstairs_vacuum_entity_is_not_required_for_ha_automation_control() -> None:
    stale_entity_id = "vacuum.valetudo_upstairs_vacuum"

    for path in (VACUUM_PATH, ZONE_PATH, ROOT / "packages" / "cleaning.yaml", ROOT / "packages" / "zigbee_zwave.yaml"):
        assert stale_entity_id not in path.read_text(encoding="utf-8")

    return_home_block = _automation_block(ZONE_PATH, "vacuum_return_home")
    assert "valetudo/upstairs-vacuum/BasicControlCapability/operation/set" in return_home_block
    assert "payload: HOME" in return_home_block


def test_departure_transition_no_longer_embeds_weekday_room_rotation() -> None:
    block = _automation_block(ZONE_PATH, "turn_off_lights_when_i_leave")

    assert "script.house_transition" in block
    assert "MapSegmentationCapability/clean/set" not in block
    assert '"iterations": 4' not in block
    assert "script.vacuum_main_and_upstairs_levels" not in block


def test_x40_mop_schedule_helpers_and_home_streak_automation_exist() -> None:
    config = VACUUM_PATH.read_text(encoding="utf-8")
    block = _automation_block(VACUUM_PATH, "x40_ultra_force_clean_after_four_home_days")

    assert "x40_ultra_mop_pass_pending:" in config
    assert "x40_ultra_last_mopped_at:" in config
    assert "input_boolean.x40_ultra_mop_pass_pending" in config
    assert "input_datetime.x40_ultra_last_mopped_at" in config
    assert "for:\n          days: 4" in block
    assert "entity_id: input_boolean.guest_mode" in block
    assert "entity_id: binary_sensor.bayesian_bed_occupancy" in block
    assert "action: script.vacuum_main_and_upstairs_levels" in block
    assert "force_mop: true" in block


def test_away_automations_use_shared_whole_floor_helper() -> None:
    automation_locations = [
        (ZONE_PATH, "vacuum_leave_home"),
        (WORKDAY_PATH, "vacuum_while_working"),
        (CURLING_PATH, "leave_home_for_curling"),
    ]

    for path, automation_id in automation_locations:
        block = _automation_block(path, automation_id)
        assert "action: script.vacuum_main_and_upstairs_levels" in block
        assert "MapSegmentationCapability/clean/set" not in block
        assert '"iterations": 4' not in block

    trip_wrapper = _script_block(TRIPS_PATH, "trip_vacuum_main_and_upstairs_levels")
    assert "action: script.vacuum_main_and_upstairs_levels" in trip_wrapper
    assert "force_mop:" in trip_wrapper

    for automation_id in ("vacuum_on_trip", "vacuum_flying_home"):
        block = _automation_block(TRIPS_PATH, automation_id)
        assert "action: script.trip_vacuum_main_and_upstairs_levels" in block
        assert "MapSegmentationCapability/clean/set" not in block
        assert '"iterations": 4' not in block

    flying_home_block = _automation_block(TRIPS_PATH, "vacuum_flying_home")
    assert "force_mop: true" in flying_home_block


def test_x40_replaces_mainlevel_vacuum_in_shared_consumers() -> None:
    stale_entity_id = "vacuum.valetudo_mainlevel"

    for path in (VACUUM_PATH, ZONE_PATH, ROOT / "packages" / "cleaning.yaml"):
        assert stale_entity_id not in path.read_text(encoding="utf-8")

    return_home_block = _automation_block(ZONE_PATH, "vacuum_return_home")
    assert "- vacuum.x40_ultra" in return_home_block
    assert stale_entity_id not in return_home_block

    cleaning_config = (ROOT / "packages" / "cleaning.yaml").read_text(encoding="utf-8")
    assert "- vacuum.x40_ultra" in cleaning_config
