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

    # Main-level launcher is fire-and-forget (script.turn_on) so callers do not
    # block for the whole run. Everything funnels through the SINGLE serialized
    # entry (policy_clean) so different X40 child scripts never overlap on the
    # device; a forced mop is expressed by marking a mop pending (a latch a
    # concurrent non-forced call cannot clear), not a separate direct route.
    assert "action: script.turn_on" in main_level_block
    assert "entity_id: script.x40_ultra_main_level_policy_clean" in main_level_block
    assert "input_boolean.x40_ultra_mop_pass_pending" in main_level_block
    assert "script.turn_on\n        target:\n          entity_id: script.x40_ultra_main_level_mop_after_vacuum" not in main_level_block
    assert "x40_ultra_force_mop_next" not in main_level_block
    assert "x40_ultra_force_mop_next" not in policy_block

    # Vacuum-only pass: CleanGenius is disabled so the cleaning-mode select can
    # be forced to sweeping, then restored. The broken custom-cleaning service
    # (which 500s while CleanGenius is active) must be gone, completion is gated
    # on the vacuum entity (never task_status), and the start is gated on the
    # mode actually becoming sweeping so a not-due run cannot mop.
    assert "entity_id: vacuum.x40_ultra" in vacuum_only_block
    assert "action: script.x40_ultra_prepare_deterministic_cleaning" in vacuum_only_block
    assert 'option: "sweeping"' in vacuum_only_block
    assert 'state: "sweeping"' in vacuum_only_block
    assert "action: vacuum.start" in vacuum_only_block
    assert "action: script.x40_ultra_wait_until_docked" in vacuum_only_block
    assert "action: script.x40_ultra_restore_cleangenius" in vacuum_only_block
    assert "dreame_vacuum.vacuum_set_custom_cleaning" not in vacuum_only_block
    assert "sensor.x40_ultra_task_status" not in vacuum_only_block

    assert "action: script.x40_ultra_main_level_mop_after_vacuum" in policy_block
    assert "action: script.x40_ultra_main_level_vacuum_only" in policy_block

    # Mop pass: vacuum-then-mop in one run via mopping_after_sweeping, CleanGenius
    # restored, and the schedule updated only on a real `completed` task status so
    # an arrival-triggered return-to-base (docked/idle without completion) can't
    # clear the mop debt. The broken multi-value task_status triggers stay gone.
    assert 'option: "mopping_after_sweeping"' in mop_after_vacuum_block
    assert "action: script.x40_ultra_restore_cleangenius" in mop_after_vacuum_block
    assert "input_boolean.x40_ultra_mop_pass_pending" in mop_after_vacuum_block
    assert "input_datetime.x40_ultra_last_mopped_at" in mop_after_vacuum_block
    assert "dreame_vacuum.vacuum_set_custom_cleaning" not in mop_after_vacuum_block
    assert "entity_id: sensor.x40_ultra_task_status" in mop_after_vacuum_block
    assert 'state: "completed"' in mop_after_vacuum_block
    assert 'to: "failed"' not in mop_after_vacuum_block
    # Robustness guards (codex P1/P2): only record a mop when the mode actually
    # applied, the robot really started, and the run reached a real finish.
    assert 'state: "mopping_after_sweeping"' in mop_after_vacuum_block
    # Start confirmation uses wait_template (passes immediately if already
    # cleaning) to avoid the wait_for_trigger already-true race.
    assert "is_state('vacuum.x40_ultra', 'cleaning')" in mop_after_vacuum_block
    assert "action: script.x40_ultra_wait_until_docked" in mop_after_vacuum_block

    # CleanGenius is toggled off then restored via dedicated helper scripts.
    prepare_block = _script_block(VACUUM_PATH, "x40_ultra_prepare_deterministic_cleaning")
    restore_block = _script_block(VACUUM_PATH, "x40_ultra_restore_cleangenius")
    assert "entity_id: select.x40_ultra_cleangenius" in prepare_block
    assert 'option: "off"' in prepare_block
    assert "select.x40_ultra_cleaning_mode" in prepare_block
    assert "entity_id: select.x40_ultra_cleangenius" in restore_block
    assert 'option: "deep_cleaning"' in restore_block

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
    block = _automation_block(ZONE_PATH, "run_verified_departure")

    assert "script.departure_integrity" in block
    assert "MapSegmentationCapability/clean/set" not in block
    assert '"iterations": 4' not in block
    assert "script.vacuum_main_and_upstairs_levels" not in block


def test_x40_mop_schedule_helpers_and_home_streak_automation_exist() -> None:
    config = VACUUM_PATH.read_text(encoding="utf-8")
    block = _automation_block(VACUUM_PATH, "x40_ultra_maintenance_clean_after_four_home_days")

    assert "x40_ultra_mop_pass_pending:" in config
    assert "x40_ultra_last_mopped_at:" in config
    assert "x40_ultra_home_since_at:" in config
    assert "input_boolean.x40_ultra_mop_pass_pending" in config
    assert "input_datetime.x40_ultra_last_mopped_at" in config
    assert "entity_id: input_boolean.guest_mode" in block
    assert "entity_id: binary_sensor.bayesian_bed_occupancy" in block
    # Main level only: it must call the X40 main-level launcher, NOT the
    # main+upstairs helper (which would run bedroom robots at 13:00 while home).
    assert "action: script.vacuum_main_level_full_floor" in block
    assert "vacuum_main_and_upstairs_levels" not in block
    assert "vacuum_upstairs_full_floor" not in block
    # Must NOT force a mop: forcing on the daily 13:00 trigger would mop every
    # day after day four; the policy's 3-day timestamp decides instead.
    assert "force_mop: true" not in block
    # The four-day streak is measured from a persistent "home since" timestamp
    # (start of the current streak), not a live state `for:` duration, so it
    # counts real occupancy and survives HA restarts.
    assert "for:\n          days: 4" not in block
    assert "input_datetime.x40_ultra_home_since_at" in block
    assert "4 * 24 * 60 * 60" in block

    # home_since is recorded by its own automation on the away->home edge (with a
    # startup seed), NOT the away edge, so a return does not pre-satisfy 4 days.
    home_block = _automation_block(VACUUM_PATH, "x40_ultra_record_home_since")
    assert "entity_id: binary_sensor.bayesian_zeke_home" in home_block
    assert 'from: "off"' in home_block
    assert 'to: "on"' in home_block
    assert "input_datetime.x40_ultra_home_since_at" in home_block


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
    # Away/trip paths may vacuum only; pet safety requires an inspected floor
    # before mopping, so flying home must no longer force a mop pass.
    assert "force_mop: true" not in flying_home_block


def test_x40_replaces_mainlevel_vacuum_in_shared_consumers() -> None:
    stale_entity_id = "vacuum.valetudo_mainlevel"

    for path in (VACUUM_PATH, ZONE_PATH, ROOT / "packages" / "cleaning.yaml"):
        assert stale_entity_id not in path.read_text(encoding="utf-8")

    return_home_block = _automation_block(ZONE_PATH, "vacuum_return_home")
    assert "- vacuum.x40_ultra" in return_home_block
    assert stale_entity_id not in return_home_block

    cleaning_config = (ROOT / "packages" / "cleaning.yaml").read_text(encoding="utf-8")
    assert "- vacuum.x40_ultra" in cleaning_config
