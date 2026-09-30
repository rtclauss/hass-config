from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
TRIP_DOC_PATH = ROOT / "docs" / "trip_mode_orchestration.md"
HOUSE_TRANSITION_DOC_PATH = ROOT / "docs" / "house_transition_framework.md"


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


def test_trip_watchdog_delegates_to_trip_mode_manager() -> None:
    block = _automation_block(TRIPS_PATH, "trip_mode_watchdog_home_1h")

    assert "event: trip_mode_resolution_requested" in block
    assert "desired_state: \"off\"" in block
    assert "reason: watchdog_home_1h" in block
    assert "action: switch.turn_off" not in block
    assert "action: input_boolean.turn_off" not in block
    assert "action: input_number.set_value" not in block


def test_trip_mode_manager_handles_watchdog_disable_through_house_transition() -> None:
    block = _automation_block(TRIPS_PATH, "trip_mode_manager")

    assert "id: watchdog_home_disable" in block
    assert "reason: watchdog_home_1h" in block
    assert "action: input_boolean.turn_off" in block
    assert "reason: watchdog_home_1h" in block
    assert "action: script.house_transition" in block
    assert "apply_trip_policy: true" in block
    assert "Trip mode watchdog cleared vacation mode after 1 hour" in block
    assert "at home." in block


def test_trip_orchestration_doc_captures_owner_and_guest_policy() -> None:
    doc = TRIP_DOC_PATH.read_text(encoding="utf-8")
    house_doc = HOUSE_TRANSITION_DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "automation.trip_mode_manager",
        "trip_mode_resolution_requested",
        "script.house_transition",
        "apply_trip_policy: true",
        "switch.vacation_simulation",
        "input_number.random_vacation_light_group",
        "input_boolean.guest_mode",
        "input_select.vacuum_pet_policy",
        "Unattended",
        "docs/room_intent.yaml",
        "vacuum_on_trip",
        "vacuum_flying_home",
    ):
        assert token in doc

    assert "docs/trip_mode_orchestration.md" in house_doc


def test_guest_door_unlock_opens_house_and_lock_closes_it() -> None:
    unlock = _automation_block(TRIPS_PATH, "trip_guest_door_unlock_open_house")
    lock = _automation_block(TRIPS_PATH, "trip_guest_door_lock_close_house")

    assert "entity_id: lock.front_door_lock" in unlock
    assert "input_boolean.trip\n" in unlock
    assert "binary_sensor.bayesian_zeke_home" in unlock
    assert "action: alarm_control_panel.alarm_disarm" in unlock
    assert "action: switch.turn_on" in unlock
    assert "switch.basement_water_shutoff" in unlock

    assert "to: locked" in lock
    assert "input_boolean.trip_guest_visit_active" in lock
    assert "action: alarm_control_panel.alarm_arm_away" in lock
    assert "action: switch.turn_off" in lock
    assert "switch.basement_water_shutoff" in lock


def test_guest_visit_flag_clears_on_return_or_trip_end() -> None:
    block = _automation_block(TRIPS_PATH, "trip_guest_visit_clear_on_return")

    assert "entity_id: binary_sensor.bayesian_zeke_home" in block
    assert "entity_id: input_boolean.trip\n" in block
    assert "action: input_boolean.turn_off" in block
    assert "input_boolean.trip_guest_visit_active" in block


def test_guest_visit_disables_cameras_vetoes_vacuum_and_verifies_relock() -> None:
    unlock = _automation_block(TRIPS_PATH, "trip_guest_door_unlock_open_house")
    lock = _automation_block(TRIPS_PATH, "trip_guest_door_lock_close_house")

    assert "switch.livingroom_motion_detection" in unlock
    assert "switch.tikiroomcam_tikiroom_motion_detection" in unlock
    assert "switch.livingroom_motion_detection" in lock

    for automation_id in ("vacuum_on_trip", "vacuum_flying_home"):
        block = _automation_block(TRIPS_PATH, automation_id)
        assert "input_boolean.trip_guest_visit_active" in block

    # The flag is cleared only after the secured state is verified.
    assert lock.index("wait_template") < lock.index("input_boolean.turn_off")
    assert "House NOT secured" in lock or "NOT secured" in lock


def test_guest_visit_hardening() -> None:
    unlock = _automation_block(TRIPS_PATH, "trip_guest_door_unlock_open_house")
    assert "from: locked" not in unlock
    assert "not_from:" in unlock
    assert "NOT ready" in unlock

    shutoff = _automation_block(
        ROOT / "packages" / "utilities.yaml", "water_shutoff_on_trip"
    )
    assert "input_boolean.trip_guest_visit_active" in shutoff


def test_relock_verifies_camera_switches_before_clearing_flag() -> None:
    lock = _automation_block(TRIPS_PATH, "trip_guest_door_lock_close_house")
    verify = lock[lock.index("wait_template") : lock.index("input_boolean.turn_off")]

    assert "is_state('switch.livingroom_motion_detection', 'on')" in verify
    assert "is_state('switch.tikiroomcam_tikiroom_motion_detection', 'on')" in verify


def test_unlock_verifies_water_alarm_and_cameras_before_success() -> None:
    unlock = _automation_block(TRIPS_PATH, "trip_guest_door_unlock_open_house")
    verify = unlock[unlock.index("wait_template") : unlock.index("House ready for guest")]

    assert "is_state('alarm_control_panel.home_alarm', 'disarmed')" in verify
    assert "is_state('switch.basement_water_shutoff', 'on')" in verify
    assert "is_state('switch.livingroom_motion_detection', 'off')" in verify
    assert "is_state('switch.tikiroomcam_tikiroom_motion_detection', 'off')" in verify
    assert "repeat:" in unlock


def test_unlock_docks_vacuums_and_relock_aborts_if_unlocked() -> None:
    unlock = _automation_block(TRIPS_PATH, "trip_guest_door_unlock_open_house")
    lock = _automation_block(TRIPS_PATH, "trip_guest_door_lock_close_house")

    assert "script.vacuum_dock_all_robots" in unlock
    guard = "entity_id: lock.front_door_lock\n              state: locked"
    assert lock.count(guard) == 2
    assert lock.index(guard) < lock.index("action: switch.turn_off")
    assert lock.rindex(guard) > lock.index("wait_template")
    assert lock.rindex(guard) < lock.index("input_boolean.turn_off")
