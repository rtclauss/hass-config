from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
CURLING_PATH = ROOT / "packages" / "curling.yaml"
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
ROOM_INTENT_PATH = ROOT / "docs" / "room_intent.yaml"
POLICY_DOC_PATH = ROOT / "docs" / "vacuum_pet_policy.md"


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
        raise AssertionError(f"Could not find automation {automation_id!r} in {path.name}")

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
        raise AssertionError(f"Could not find script {script_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            end = index
            break
    return "\n".join(lines[start:end])


def _assert_unattended_gate(block: str) -> None:
    assert "condition: state" in block
    assert "entity_id: input_select.vacuum_pet_policy" in block
    assert 'state: "Unattended"' in block


def test_pet_policy_helper_defaults_fail_closed_after_reload() -> None:
    config = VACUUM_PATH.read_text(encoding="utf-8")
    helper = config.split("  vacuum_pet_policy:", 1)[1].split("\n\n", 1)[0]

    assert "name: Vacuum Pet Safety Policy" in helper
    assert "- Acclimation" in helper
    assert "- Supervised" in helper
    assert "- Unattended" in helper
    assert "initial: Acclimation" in helper


def test_every_automatic_cleaning_path_routes_through_a_pet_safe_boundary() -> None:
    shared_floor_callers = (
        (ZONE_PATH, "vacuum_leave_home"),
        (WORKDAY_PATH, "vacuum_while_working"),
        (CURLING_PATH, "leave_home_for_curling"),
    )
    for path, automation_id in shared_floor_callers:
        block = _automation_block(path, automation_id)
        assert "action: script.vacuum_main_and_upstairs_levels" in block

    maintenance = _automation_block(VACUUM_PATH, "x40_ultra_maintenance_clean_after_four_home_days")
    assert "action: script.vacuum_main_level_full_floor" in maintenance

    for automation_id in ("vacuum_on_trip", "vacuum_flying_home"):
        trip = _automation_block(TRIPS_PATH, automation_id)
        assert "action: script.trip_vacuum_main_and_upstairs_levels" in trip

    den_retry = _automation_block(VACUUM_PATH, "resume_vacuum_on_error_den")
    departure = _automation_block(ZONE_PATH, "vacuum_leave_home")
    assert "action: script.vacuum_den_pet_safe_start" in den_retry
    assert "action: script.vacuum_den_pet_safe_start" in departure


def test_shared_full_floor_boundaries_fail_closed_for_unknown_or_disabled_policy() -> None:
    for script_id in (
        "vacuum_den_pet_safe_start",
        "x40_ultra_main_level_vacuum_only",
        "vacuum_main_level_full_floor",
        "vacuum_main_and_upstairs_levels",
        "x40_ultra_main_level_mop_after_vacuum",
        "x40_ultra_main_level_mop_only",
        "trip_vacuum_main_and_upstairs_levels",
    ):
        path = TRIPS_PATH if script_id == "trip_vacuum_main_and_upstairs_levels" else VACUUM_PATH
        _assert_unattended_gate(_script_block(path, script_id))


def test_entering_acclimation_immediately_docks_all_robots() -> None:
    automation = _automation_block(VACUUM_PATH, "vacuum_pet_policy_acclimation_dock")
    dock_script = _script_block(VACUUM_PATH, "vacuum_dock_all_robots")

    assert "entity_id: input_select.vacuum_pet_policy" in automation
    assert 'to: "Acclimation"' in automation
    assert "action: script.vacuum_dock_all_robots" in automation
    assert dock_script.count("action: vacuum.return_to_base") == 2
    assert "entity_id: vacuum.valetudo_den" in dock_script
    assert "entity_id: vacuum.x40_ultra" in dock_script
    assert "valetudo/upstairs-vacuum/BasicControlCapability/operation/set" in dock_script
    assert "payload: HOME" in dock_script
    assert dock_script.count("continue_on_error: true") == 3


def test_supervised_launcher_is_gated_and_vacuum_only() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_supervised_clean")

    # Allowed under Supervised or Unattended (owner present), never Acclimation.
    assert "entity_id: input_select.vacuum_pet_policy" in block
    assert '- "Supervised"' in block
    assert '- "Unattended"' in block
    # Guest mode still vetoes.
    assert "entity_id: input_boolean.guest_mode" in block
    assert 'state: "off"' in block
    # Vacuum-only: never launches a mop path from the supervised launcher.
    assert "script.x40_ultra_main_level_mop" not in block
    assert 'option: "mopping"' not in block
    # Upstairs Valetudo rooms (vacuum-only hardware) dispatch to their scripts.
    assert "action: script.vacuum_master_bedroom" in block
    # X40 rooms must route through the deterministic sweeping launcher (which
    # forces sweeping), NOT the raw segment scripts that could mop under
    # CleanGenius.
    assert "action: script.x40_ultra_segment_vacuum_only" in block
    assert "action: script.vacuum_kitchen" not in block
    assert "action: script.vacuum_living_room" not in block


def test_supervised_x40_segment_launcher_forces_sweeping() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_segment_vacuum_only")

    # CleanGenius off, mode forced to sweeping and verified before any start, so
    # a leftover mopping mode cannot mop during a "vacuum-only" supervised run.
    assert "action: script.x40_ultra_prepare_deterministic_cleaning" in block
    assert 'option: "sweeping"' in block
    assert 'state: "sweeping"' in block
    prepare = block.index("action: script.x40_ultra_prepare_deterministic_cleaning")
    guard = block.index('state: "sweeping"', prepare)
    start = block.index("action: dreame_vacuum.vacuum_clean_segment", guard)
    assert prepare < guard < start
    assert "action: script.x40_ultra_restore_cleangenius" in block


def test_trip_path_cleans_all_three_areas() -> None:
    trip_wrapper = _script_block(TRIPS_PATH, "trip_vacuum_main_and_upstairs_levels")

    # Main + upstairs via the shared helper, and the den via its pet-safe
    # boundary, so trip/flying-home days cover the same areas as departure.
    assert "action: script.vacuum_main_and_upstairs_levels" in trip_wrapper
    assert "action: script.vacuum_den_pet_safe_start" in trip_wrapper


def test_mopping_only_runs_under_unattended_even_when_forced() -> None:
    policy = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    trip_wrapper = _script_block(TRIPS_PATH, "trip_vacuum_main_and_upstairs_levels")
    flying_home = _automation_block(TRIPS_PATH, "vacuum_flying_home")

    # The mop schedule itself is gated on Unattended...
    assert "is_state('input_select.vacuum_pet_policy', 'Unattended')" in policy
    # ...and flying home may force a mop, but only after the trip wrapper's
    # Unattended condition passes, so a forced mop still fails closed.
    assert "force_mop: true" in flying_home
    _assert_unattended_gate(trip_wrapper)


def test_x40_rechecks_policy_after_preparation_and_before_each_start() -> None:
    for script_id in (
        "x40_ultra_main_level_vacuum_only",
        "x40_ultra_main_level_mop_only",
    ):
        block = _script_block(VACUUM_PATH, script_id)
        prepare = block.index("action: script.x40_ultra_prepare_deterministic_cleaning")
        policy_recheck = block.index(
            "entity_id: input_select.vacuum_pet_policy",
            prepare,
        )
        start = block.index("action: vacuum.start", policy_recheck)

        assert prepare < policy_recheck < start


def test_main_level_mop_after_vacuum_is_two_ordered_passes() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    vacuum_pass = block.index("action: script.x40_ultra_main_level_vacuum_only")
    mop_pass = block.index("action: script.x40_ultra_main_level_mop_only")

    # Vacuum the whole floor first, then mop — dry debris up before any water.
    assert vacuum_pass < mop_pass
    # The orchestrator delegates the device work; it must not start the robot
    # itself or select the interleaved sweep+mop mode.
    assert "action: vacuum.start" not in block
    assert 'option: "mopping_after_sweeping"' not in block

    mop_only = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_only")
    # The mop pass is a dedicated mop-only run and owns the schedule bookkeeping.
    assert 'option: "mopping"' in mop_only
    assert "entity_id: input_datetime.x40_ultra_last_mopped_at" in mop_only
    assert "entity_id: input_boolean.x40_ultra_mop_pass_pending" in mop_only


def test_mop_is_gated_on_a_completed_vacuum_pass() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    # The mop must only start after the vacuum pass reached a real `completed`
    # task status. An arrival-triggered return-to-base or a no-op start docks the
    # robot WITHOUT completion, so the mop is skipped — preserving both the
    # arrival-to-dock protection and the vacuum-before-water ordering.
    vacuum_pass = block.index("action: script.x40_ultra_main_level_vacuum_only")
    completion_gate = block.index("entity_id: sensor.x40_ultra_task_status", vacuum_pass)
    mop_pass = block.index("action: script.x40_ultra_main_level_mop_only", completion_gate)
    assert vacuum_pass < completion_gate < mop_pass
    assert 'state: "completed"' in block


def test_room_intent_links_durable_cat_safe_cleaning_policy() -> None:
    room_intent = ROOM_INTENT_PATH.read_text(encoding="utf-8")
    policy = POLICY_DOC_PATH.read_text(encoding="utf-8")

    assert "cat_safe_robot_cleaning" in room_intent
    assert "docs/vacuum_pet_policy.md" in room_intent
    assert "Acclimation" in policy
    assert "Supervised" in policy
    assert "Unattended" in policy
    assert "owner decision" in policy
    assert "robot-free refuge" in policy
