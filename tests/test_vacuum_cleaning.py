from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
CURLING_PATH = ROOT / "packages" / "curling.yaml"
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
ROOM_INTENT_PATH = ROOT / "docs" / "room_intent.yaml"
CLEANING_DOC_PATH = ROOT / "docs" / "vacuum_cleaning.md"
TEMPLATE_PATHS = (
    ROOT / "private_templates" / "xiaomi_robot_vacuum.yaml.tmpl",
    ROOT / "private_templates" / "trips.yaml.tmpl",
    ROOT / "private_templates" / "zone.yaml.tmpl",
)


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


def test_pet_policy_is_fully_removed() -> None:
    # The owner removed the cat pet-safety policy; no helper, gate, automation,
    # or room-intent rule may still reference it.
    for path in TEMPLATE_PATHS:
        text = path.read_text(encoding="utf-8")
        for needle in (
            "vacuum_pet_policy",
            "Unattended",
            "Acclimation",
            "Supervised",
            "pet_safe",
            "input_select.vacuum_room",
        ):
            assert needle not in text, f"{needle!r} still in {path.name}"
    room_intent = ROOM_INTENT_PATH.read_text(encoding="utf-8")
    assert "cat_safe_robot_cleaning" not in room_intent
    assert not (ROOT / "docs" / "vacuum_pet_policy.md").exists()


def test_restart_no_longer_docks_every_robot() -> None:
    config = VACUUM_PATH.read_text(encoding="utf-8")
    assert "vacuum_pet_policy_acclimation_dock" not in config
    assert "vacuum_dock_supervised_on_presence_loss" not in config


def test_every_automatic_cleaning_path_routes_through_a_guarded_boundary() -> None:
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
    assert "action: script.vacuum_den_guarded_start" in den_retry
    assert "action: script.vacuum_den_guarded_start" in departure


def test_den_error_retry_ignores_the_restart_transition() -> None:
    # The entity reconnects through unknown/unavailable after a restart; that
    # transient -> error must not auto-start the den robot.
    block = _automation_block(VACUUM_PATH, "resume_vacuum_on_error_den")

    assert "not_from:" in block
    assert '- "unknown"' in block
    assert '- "unavailable"' in block
    assert "action: script.vacuum_den_guarded_start" in block


def test_den_boundary_keeps_guest_and_door_guards() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_den_guarded_start")
    start = block.index("action: vacuum.start")
    assert block.index("entity_id: input_boolean.guest_mode") < start
    assert block.index("entity_id: input_boolean.trip_guest_visit_active") < start
    assert block.index("entity_id: binary_sensor.den_doors_contact") < start


def test_dock_all_robots_covers_all_three() -> None:
    dock_script = _script_block(VACUUM_PATH, "vacuum_dock_all_robots")

    assert dock_script.count("action: vacuum.return_to_base") == 2
    assert "entity_id: vacuum.valetudo_den" in dock_script
    assert "entity_id: vacuum.x40_ultra" in dock_script
    assert "valetudo/upstairs-vacuum/BasicControlCapability/operation/set" in dock_script
    assert "payload: HOME" in dock_script
    assert dock_script.count("continue_on_error: true") == 3


def test_manual_start_routes_every_robot_through_guarded_scripts() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_manual_start")

    assert "robot:" in block
    assert "action: script.vacuum_main_level_full_floor" in block
    assert "action: script.vacuum_upstairs_full_floor" in block
    assert "action: script.vacuum_den_guarded_start" in block
    # "all" runs all three robots.
    for want in ("want_main", "want_upstairs", "want_den"):
        assert re.search(rf"{want}: .*'all'", block), want
    # Never a raw start that would bypass the guards or the X40 sweeping flow.
    assert "action: vacuum.start" not in block
    assert "vacuum.clean_area" not in block.split("sequence:", 1)[1]
    assert "payload: START" not in block
    # The main level lets the dispatcher decide the mop (no forced flag).
    assert "force_mop" not in block
    # A blocked start notifies instead of failing silently, before any start.
    first_start = block.index("action: script.vacuum_main_level_full_floor")
    assert block.index("input_boolean.guest_mode") < first_start
    assert block.index("input_boolean.trip_guest_visit_active") < first_start
    assert block.index("action: notify.all") < first_start
    # The den reports an open door rather than silently skipping.
    den = block.index("action: script.vacuum_den_guarded_start")
    assert block.index("entity_id: binary_sensor.den_doors_contact") < den
    assert "den doors are not confirmed" in block


def test_room_launcher_takes_the_room_as_a_field_and_is_vacuum_only() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_clean_room")

    # A call-time field, never the old shared selector, so a queued request
    # cleans exactly the tapped room.
    assert "fields:\n      room:" in block
    assert "input_select" not in block
    # X40 rooms go through the single dispatcher as a segment run (forces
    # sweeping, serializes with automatic runs); upstairs rooms through the
    # guarded upstairs boundary.
    assert "entity_id: script.x40_ultra_main_level_policy_clean" in block
    assert "kind: segment" in block
    assert "entity_id: script.vacuum_upstairs_segment_guarded" in block
    # Vacuum-only: no mop path, no raw segment/start calls.
    assert "mop" not in block.split("sequence:", 1)[1]
    assert "dreame_vacuum.vacuum_clean_segment" not in block
    assert "action: vacuum.start" not in block
    assert "action: script.vacuum_kitchen" not in block
    # Guest veto notifies before any dispatch.
    dispatch = block.index("entity_id: script.x40_ultra_main_level_policy_clean")
    assert block.index("input_boolean.guest_mode") < dispatch
    assert block.index("action: notify.all") < dispatch


def test_room_launcher_maps_x40_rooms_to_the_entity_area_mapping() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_clean_room")
    x40 = dict(re.findall(r"^        ([a-z_]+): (\d)$", block, re.MULTILINE))
    assert x40 == {
        "dining_room": "1",
        "powder_room": "2",
        "hallway": "3",
        "kitchen": "4",
        "den": "5",
        "laundry_room": "6",
    }
    upstairs = dict(re.findall(r"^        ([a-z_]+): (script\.[a-z_]+)$", block, re.MULTILINE))
    assert upstairs == {
        "bedroom": "script.vacuum_master_bedroom",
        "guest_room": "script.vacuum_guest_room",
        "bathroom": "script.vacuum_bathroom",
        "upstairs_hallway": "script.vacuum_hallway",
        "office": "script.vacuum_office",
    }


def test_upstairs_boundary_rechecks_guest_and_holds_until_terminal() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_upstairs_segment_guarded")

    guest = block.index("entity_id: input_boolean.guest_mode")
    delegate = block.index("{{ room_script }}")
    assert guest < delegate
    # mode: queued plus the terminal hold serializes upstairs room requests. It
    # tracks the run via the Valetudo MQTT status topic, NOT the flaky vacuum
    # entity the config avoids by design.
    assert "mode: queued" in block
    assert "valetudo/upstairs-vacuum/StatusStateAttribute/status" in block
    assert "vacuum.valetudo_upstairs_vacuum" not in block
    hold = block.index("payload: docked", delegate)
    assert delegate < hold


def test_start_blocker_sensor_mirrors_the_launcher_guards() -> None:
    config = VACUUM_PATH.read_text(encoding="utf-8")
    sensor = config.split("default_entity_id: sensor.vacuum_start_blocker", 1)[1].split("\n\n", 1)[0]
    assert "input_boolean.guest_mode" in sensor
    assert "input_boolean.trip_guest_visit_active" in sensor
    assert "den_doors_closed" in sensor
    for state in ("guest_mode", "trip_guest", "ok"):
        assert state in sensor


def test_notifications_link_to_the_live_cleaning_view() -> None:
    for path in TEMPLATE_PATHS[:2]:
        text = path.read_text(encoding="utf-8")
        assert 'new-mushroom/cleaning"' not in text
        assert 'new-mushroom/cleaning-v2"' in text


def test_x40_segment_launcher_forces_sweeping() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_segment_vacuum_only")

    # CleanGenius off, mode forced to sweeping and verified before any start, so
    # a leftover mopping mode cannot mop during a vacuum-only room run.
    assert "action: script.x40_ultra_prepare_deterministic_cleaning" in block
    assert 'option: "sweeping"' in block
    assert 'state: "sweeping"' in block
    prepare = block.index("action: script.x40_ultra_prepare_deterministic_cleaning")
    guard = block.index('state: "sweeping"', prepare)
    start = block.index("action: dreame_vacuum.vacuum_clean_segment", guard)
    assert prepare < guard < start
    assert "action: script.x40_ultra_restore_cleangenius" in block
    # The dispatcher's entry idle/docked check can go stale during the up-to-30s
    # CleanGenius wait, so the child must recheck the X40 is at rest immediately
    # before dispatch — else an external run started mid-wait would be treated as
    # our start and have CleanGenius restored around it.
    rest = block.index("entity_id: vacuum.x40_ultra", guard)
    assert guard < rest < start
    assert '- "docked"' in block
    assert '- "idle"' in block
    # Rest must also be gated BEFORE any mutation: the entry idle/docked check
    # comes before prepare_deterministic_cleaning, so a busy robot is left fully
    # untouched (no CleanGenius/mode change at all).
    entry_rest = block.index("entity_id: vacuum.x40_ultra")
    assert entry_rest < prepare
    # And CleanGenius is not restored on top of an external run: a wait for the
    # robot to return to rest precedes the restore.
    restore = block.index("action: script.x40_ultra_restore_cleangenius")
    wait_before_restore = block.rindex(
        "states('vacuum.x40_ultra') in ['docked', 'idle']", 0, restore
    )
    assert wait_before_restore < restore
    # That wait must fail closed: an external run can take up to 6h, so it must
    # not bypass to restore after a short timeout and change CleanGenius mid-run.
    fail_closed = block.index("continue_on_timeout: false", wait_before_restore)
    assert wait_before_restore < fail_closed < restore
    # Guest mode is also rechecked between the sweeping guard and the dispatch
    # (it can change during the up-to-30s CleanGenius wait).
    guest_recheck = block.index("entity_id: input_boolean.guest_mode", guard)
    assert guard < guest_recheck < start


def test_mode_select_is_rechecked_for_rest_after_preparation() -> None:
    # The entry/dispatcher rest check can go stale during prepare's up-to-30s
    # wait, so each child must recheck rest AFTER preparation and BEFORE selecting
    # the cleaning mode — never changing the mode on a robot an external run grabbed.
    for script_id, mode in (
        ("x40_ultra_main_level_vacuum_only", "sweeping"),
        ("x40_ultra_main_level_mop_only", "mopping"),
        ("x40_ultra_segment_vacuum_only", "sweeping"),
    ):
        block = _script_block(VACUUM_PATH, script_id)
        prepare = block.index("action: script.x40_ultra_prepare_deterministic_cleaning")
        select = block.index(f'option: "{mode}"', prepare)
        rest = block.rindex("entity_id: vacuum.x40_ultra", prepare, select)
        assert prepare < rest < select


def test_full_floor_children_wait_for_rest_before_restoring_cleangenius() -> None:
    # Both full-floor children must defer restoring CleanGenius until the robot is
    # at rest (fail closed), so a manual/app run started during prep — or their
    # own pass still active if wait_until_docked timed out — does not get
    # CleanGenius re-enabled mid-run.
    for script_id in (
        "x40_ultra_main_level_vacuum_only",
        "x40_ultra_main_level_mop_only",
    ):
        block = _script_block(VACUUM_PATH, script_id)
        restore = block.index("action: script.x40_ultra_restore_cleangenius")
        wait_rest = block.rindex(
            "states('vacuum.x40_ultra') in ['docked', 'idle']", 0, restore
        )
        fail_closed = block.index("continue_on_timeout: false", wait_rest)
        assert wait_rest < fail_closed < restore


def test_trip_path_cleans_all_three_areas() -> None:
    trip_wrapper = _script_block(TRIPS_PATH, "trip_vacuum_main_and_upstairs_levels")

    # Main + upstairs via the shared helper, and the den via its guarded
    # boundary, so trip/flying-home days cover the same areas as departure.
    assert "action: script.vacuum_main_and_upstairs_levels" in trip_wrapper
    assert "action: script.vacuum_den_guarded_start" in trip_wrapper


def test_flying_home_may_force_a_mop() -> None:
    policy = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    flying_home = _automation_block(TRIPS_PATH, "vacuum_flying_home")

    assert "force_mop: true" in flying_home
    assert "allow_mop | default(true) | bool" in policy


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


def test_mop_is_gated_on_a_run_scoped_completed_vacuum_pass() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    # The mop must only start when THIS vacuum pass completed, read from the
    # run-scoped latch — NOT the ambient task_status, which can still read
    # `completed` from an earlier run when the new pass never started. An
    # arrival-triggered return-to-base or a no-op start leaves the latch off, so
    # the mop is skipped (preserving arrival-to-dock + vacuum-before-water).
    vacuum_pass = block.index("action: script.x40_ultra_main_level_vacuum_only")
    completion_gate = block.index(
        "entity_id: input_boolean.x40_ultra_vacuum_pass_completed", vacuum_pass
    )
    mop_pass = block.index("action: script.x40_ultra_main_level_mop_only", completion_gate)
    assert vacuum_pass < completion_gate < mop_pass
    assert 'state: "on"' in block
    # The gate must not rely on the ambient task_status sensor.
    assert "entity_id: sensor.x40_ultra_task_status" not in block


def test_full_floor_starts_recheck_guest_mode_before_start() -> None:
    # Guest mode can be enabled during the (up-to-30s) CleanGenius wait or the
    # hours-long vacuum pass; both starts must recheck the guest veto right
    # before vacuum.start.
    for script_id in (
        "x40_ultra_main_level_vacuum_only",
        "x40_ultra_main_level_mop_only",
    ):
        block = _script_block(VACUUM_PATH, script_id)
        prepare = block.index("action: script.x40_ultra_prepare_deterministic_cleaning")
        guest = block.index("entity_id: input_boolean.guest_mode", prepare)
        start = block.index("action: vacuum.start", guest)
        assert prepare < guest < start


def test_full_floor_starts_require_robot_at_rest_before_starting() -> None:
    # If the X40 is already `cleaning` (manual/app/segment run), our vacuum.start
    # would be a no-op and the start-confirmation would credit that unrelated run
    # as the full-floor pass/mop. Both starts must require an idle/docked robot.
    for script_id in (
        "x40_ultra_main_level_vacuum_only",
        "x40_ultra_main_level_mop_only",
    ):
        block = _script_block(VACUUM_PATH, script_id)
        rest_guard = block.index("entity_id: vacuum.x40_ultra")
        start = block.index("action: vacuum.start", rest_guard)
        # The rest guard (docked/idle) sits in the pre-start condition block.
        assert rest_guard < start
        assert '- "docked"' in block
        assert '- "idle"' in block


def test_single_queued_dispatcher_serializes_full_floor_and_segment() -> None:
    # Both the automatic full-floor path and the room segment path are
    # invocations of ONE mode:queued script, so the queue serializes them
    # atomically — no separate lock (and its non-atomic check-then-set) needed.
    dispatcher = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    assert "mode: queued" in dispatcher
    # Full-floor branch invokes the mop/vacuum children; the segment branch
    # invokes the segment script — both live inside this one queued script.
    assert "action: script.x40_ultra_main_level_mop_after_vacuum" in dispatcher
    assert "action: script.x40_ultra_main_level_vacuum_only" in dispatcher
    assert "action: script.x40_ultra_segment_vacuum_only" in dispatcher
    assert "kind | default('full_floor')" in dispatcher

    # The full-floor launcher and the X40 rooms both route through it.
    full_floor_launcher = _script_block(VACUUM_PATH, "vacuum_main_level_full_floor")
    assert "script.x40_ultra_main_level_policy_clean" in full_floor_launcher
    room = _script_block(VACUUM_PATH, "vacuum_clean_room")
    assert "entity_id: script.x40_ultra_main_level_policy_clean" in room
    assert "kind: segment" in room

    # The lock helper and its acquire/release are gone (replaced by the queue).
    config = VACUUM_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_deterministic_lock" not in config


def test_upstairs_launch_rechecks_guest_before_start() -> None:
    block = _script_block(VACUUM_PATH, "vacuum_upstairs_full_floor")
    guest = block.index("entity_id: input_boolean.guest_mode")
    start = block.index("payload: START")
    assert guest < start


def test_dispatcher_skips_when_x40_busy_with_external_run() -> None:
    # An external manual/app run does not go through our queue, so the dispatcher
    # must require the X40 at rest before touching CleanGenius / the mode.
    dispatcher = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    rest_guard = dispatcher.index("entity_id: vacuum.x40_ultra")
    branch = dispatcher.index(
        "action: script.x40_ultra_main_level_vacuum_only", rest_guard
    )
    assert rest_guard < branch
    assert '- "docked"' in dispatcher
    assert '- "idle"' in dispatcher


def test_x40_segment_waits_for_dock_before_restoring_cleangenius() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_segment_vacuum_only")

    # vacuum_clean_segment only dispatches, so the launcher must hold sweeping
    # until the run reaches a terminal dock, then restore CleanGenius — otherwise
    # CleanGenius is re-enabled mid-sweep.
    segment = block.index("action: dreame_vacuum.vacuum_clean_segment")
    wait_dock = block.index("action: script.x40_ultra_wait_until_docked", segment)
    restore = block.index("action: script.x40_ultra_restore_cleangenius", wait_dock)
    assert segment < wait_dock < restore


def test_cleaning_doc_documents_dashboard_controls() -> None:
    doc = CLEANING_DOC_PATH.read_text(encoding="utf-8")
    assert "script.vacuum_manual_start" in doc
    assert "script.vacuum_clean_room" in doc
    assert "sensor.vacuum_start_blocker" in doc
    assert "never calls `vacuum.start`, `vacuum.clean_area`" in doc
