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
    upstairs_block = _script_block(VACUUM_PATH, "vacuum_upstairs_full_floor")

    assert "action: script.vacuum_main_level_full_floor" in helper_block
    assert "action: script.vacuum_upstairs_full_floor" in helper_block
    assert "MapSegmentationCapability/clean/set" not in helper_block
    assert '"iterations": 4' not in helper_block

    assert "entity_id: vacuum.valetudo_mainlevel" in main_level_block
    assert "action: vacuum.start" in main_level_block
    assert "entity_id: vacuum.valetudo_upstairs_vacuum" in upstairs_block
    assert "action: vacuum.start" in upstairs_block


def test_departure_transition_no_longer_embeds_weekday_room_rotation() -> None:
    block = _automation_block(ZONE_PATH, "turn_off_lights_when_i_leave")

    assert "script.house_transition" in block
    assert "MapSegmentationCapability/clean/set" not in block
    assert '"iterations": 4' not in block
    assert "script.vacuum_main_and_upstairs_levels" not in block


def test_away_automations_use_shared_whole_floor_helper() -> None:
    automation_locations = [
        (ZONE_PATH, "vacuum_leave_home"),
        (WORKDAY_PATH, "vacuum_while_working"),
        (TRIPS_PATH, "vacuum_on_trip"),
        (TRIPS_PATH, "vacuum_flying_home"),
        (CURLING_PATH, "leave_home_for_curling"),
    ]

    for path, automation_id in automation_locations:
        block = _automation_block(path, automation_id)
        assert "action: script.vacuum_main_and_upstairs_levels" in block
        assert "MapSegmentationCapability/clean/set" not in block
        assert '"iterations": 4' not in block
