from __future__ import annotations

import re
from pathlib import Path


HOLIDAYS_PATH = Path(__file__).resolve().parents[1] / "packages" / "holidays.yaml"


def _automation_block(automation_id: str) -> str:
    lines = HOLIDAYS_PATH.read_text(encoding="utf-8").splitlines()
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
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_two_minute_holiday_loops_use_half_minute_indexing() -> None:
    st_andrews = _automation_block("st_andrews_day_light_loop")
    halloween = _automation_block("halloween_light_loop")

    assert 'minutes: "/2"' in st_andrews
    assert 'minutes: "/2"' in halloween

    assert (
        "scene.scene_st_andrews_day_outdoors_{{ (now().minute // 2) % 4 + 1 | int }}"
        in st_andrews
    )
    assert "scene.scene_st_andrews_day_outdoors_{{ now().minute % 4 + 1 | int }}" not in st_andrews

    assert (
        "scene.scene_halloween_outdoors_{{ (now().minute // 2) % 4 + 1 | int }}" in halloween
    )
    assert "scene.scene_halloween_outdoors_{{ now().minute % 4 + 1 | int }}" not in halloween


def test_two_minute_holiday_loops_can_reach_all_four_scenes() -> None:
    scene_indexes = {(minute // 2) % 4 + 1 for minute in range(0, 60, 2)}

    assert scene_indexes == {1, 2, 3, 4}


def test_christmas_loop_keeps_per_minute_rotation() -> None:
    christmas = _automation_block("christmas_outside_light_loop_1")

    assert 'minutes: "/1"' in christmas
    assert "scene.scene_christmas_outdoors_{{ now().minute % 4 + 1 | int }}" in christmas

    scene_indexes = {minute % 4 + 1 for minute in range(60)}
    assert scene_indexes == {1, 2, 3, 4}
