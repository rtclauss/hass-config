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


def test_owner_suite_morning_transition_keeps_adaptive_lighting_in_control_and_delays_blind_ramp() -> None:
    block = _script_block(WORKDAY_PATH, "owner_suite_morning_transition")

    for token in (
        "script.house_transition",
        "mode: home",
        "switch.sleep_mode",
        "switch.adaptive_lighting_owner_suite",
        "action: adaptive_lighting.apply",
        "entity_id: switch.adaptive_lighting_owner_suite",
        "manual_control: true",
        "manual_control: false",
        "transition: 2",
        "transition: 180",
        "seconds: 180",
        "seconds: 175",
        "cover.owner_suite_blinds_ha",
        "position: \"{{ repeat.index * 2 }}\"",
        "switch.adaptive_lighting_adapt_brightness_owner_suite",
        "switch.adaptive_lighting_adapt_color_owner_suite",
    ):
        assert token in block


def test_wake_up_script_uses_shared_owner_suite_morning_transition() -> None:
    block = _script_block(WORKDAY_PATH, "wake_up_script")

    assert "script.owner_suite_morning_transition" in block
    assert "cover.owner_suite_blinds_ha" not in block
    assert "transition: 180" not in block


def test_workday_morning_activity_can_start_owner_suite_wake_transition() -> None:
    block = _automation_block(WORKDAY_PATH, "workday_owner_suite_wake_transition_from_morning_activity")

    for token in (
        'after: "04:30:00"',
        'before: "12:00:00"',
        "input_select.house_mode",
        "- night",
        "- in_bed",
        "- asleep",
        "binary_sensor.workday_sensor",
        "binary_sensor.bayesian_zeke_home",
        "binary_sensor.planned_vacation_calendar",
        "binary_sensor.bayesian_bed_occupancy",
        "binary_sensor.bedroom_occupancy",
        "binary_sensor.owner_suite_bathroom_room_occupancy",
        "input_boolean.wakeup_alarm_firing",
        "light.owner_suite_lamps",
        "script.owner_suite_morning_transition",
        "as_timestamp(now()) - as_timestamp(states.binary_sensor.bedroom_occupancy.last_changed) <= 900",
        "as_timestamp(now()) - as_timestamp(states.binary_sensor.owner_suite_bathroom_room_occupancy.last_changed) <= 900",
    ):
        assert token in block


def test_close_owner_suite_blinds_catches_evening_recovery_after_missed_sunset() -> None:
    block = _automation_block(WINDOWS_PATH, "close_owner_suite_blinds_at_night")

    assert 'id: sunset' in block
    assert 'from: "unavailable"' in block
    assert 'from: "unknown"' in block
    assert 'to: "open"' in block
    assert 'id: recovery' in block
    assert 'after: sunset' in block
    assert 'after_offset: -00:45:00' in block
    assert 'before: sunset' in block
    assert 'before_offset: "+00:02:00"' in block
    assert "blind_close_delay_minutes: \"{{ range(0, 48) | random | int }}\"" in block
    assert 'minutes: "{{ blind_close_delay_minutes }}"' in block
    assert "offset: -00:45:00" in block
    assert "range(0, 24)" not in block
    assert "range(5, 45)" not in block
    assert "action: cover.close_cover" in block
    assert "cover.owner_suite_blinds_ha" in block


def test_close_owner_suite_blinds_sunset_path_does_not_require_open_state() -> None:
    block = _automation_block(WINDOWS_PATH, "close_owner_suite_blinds_at_night")
    sunset_marker = "              - condition: trigger\n                id: sunset"
    sunset_branch = block.split(sunset_marker, 1)[1].split("          - conditions:", 1)[0]

    assert "condition: state" not in sunset_branch
    assert 'state: "open"' not in sunset_branch
