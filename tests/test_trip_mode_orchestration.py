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
        "docs/room_intent.yaml",
        "vacuum_on_trip",
        "vacuum_flying_home",
    ):
        assert token in doc

    assert "docs/trip_mode_orchestration.md" in house_doc
