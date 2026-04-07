from __future__ import annotations

import re
from pathlib import Path


HOUSE_MODE_PATH = Path(__file__).resolve().parents[1] / "packages" / "house_mode.yaml"
ZONE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zone.yaml"


def _script_block(script_id: str) -> str:
    lines = HOUSE_MODE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
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


def test_house_transition_no_longer_queues_later_mode_changes() -> None:
    text = _script_block("house_transition")

    assert "house_transition:" in text
    assert "mode: restart" in text
    assert "script.lights_off_except" in text


def test_departure_house_transition_runs_in_parallel_without_embedding_vacuum_logic() -> None:
    transition_block = _automation_block(ZONE_PATH, "turn_off_lights_when_i_leave")
    vacuum_block = _automation_block(ZONE_PATH, "vacuum_leave_home")

    assert "parallel:" in transition_block
    assert "action: script.house_transition" in transition_block
    assert "action: mqtt.publish" not in transition_block
    assert "action: script.vacuum_main_and_upstairs_levels" not in transition_block
    assert "action: script.vacuum_main_and_upstairs_levels" in vacuum_block
