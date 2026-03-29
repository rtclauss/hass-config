from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"


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


def test_den_vacuum_error_retry_requires_the_den_door_to_be_closed() -> None:
    block = _automation_block(VACUUM_PATH, "resume_vacuum_on_error_den")

    assert "condition:" in block
    assert "entity_id: binary_sensor.den_doors_contact" in block
    assert 'state: "off"' in block
    assert "action: vacuum.start" in block
    assert "entity_id: vacuum.valetudo_den" in block


def test_leave_home_only_starts_the_den_vacuum_when_the_den_door_is_closed() -> None:
    block = _automation_block(ZONE_PATH, "vacuum_leave_home")

    assert "entity_id: vacuum.valetudo_mainlevel" in block
    assert "entity_id: vacuum.valetudo_upstairs_vacuum" in block
    assert "- if:" in block
    assert "entity_id: binary_sensor.den_doors_contact" in block
    assert 'state: "off"' in block
    assert "entity_id: vacuum.valetudo_den" in block
