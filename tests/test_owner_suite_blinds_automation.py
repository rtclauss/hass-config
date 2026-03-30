from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PATH = ROOT / "packages" / "windows.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"


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
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and lines[index].endswith(":") and not lines[index].startswith("    "):
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


def test_wake_up_script_uses_supported_color_temperature_fields() -> None:
    block = _script_block(WORKDAY_PATH, "wake_up_script")

    assert "cover.owner_suite_blinds_ha" in block
    assert "color_temp_kelvin: 2700" in block
    assert "color_temp_kelvin: 6500" in block
    assert "\n          kelvin:" not in block


def test_close_owner_suite_blinds_catches_evening_recovery_after_missed_sunset() -> None:
    block = _automation_block(WINDOWS_PATH, "close_owner_suite_blinds_at_night")

    assert 'id: sunset' in block
    assert 'from: "unavailable"' in block
    assert 'from: "unknown"' in block
    assert 'to: "open"' in block
    assert 'id: recovery' in block
    assert 'after: sunset' in block
    assert 'before: "23:00:00"' in block
    assert 'minutes: "{{ blind_close_delay_minutes }}"' in block
    assert "action: cover.close_cover" in block
    assert "cover.owner_suite_blinds_ha" in block
