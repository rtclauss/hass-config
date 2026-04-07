from __future__ import annotations

import re
from pathlib import Path


UTILITIES_PATH = Path(__file__).resolve().parents[1] / "packages" / "utilities.yaml"


def _automation_block(automation_id: str) -> str:
    lines = UTILITIES_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line != f"    id: {automation_id}":
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - alias: "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    next_automation = re.compile(r"^  - alias: ")
    for index in range(start + 1, len(lines)):
        if next_automation.match(lines[index]):
            end = index
            break

    block = "\n".join(lines[start:end])
    assert f"id: {automation_id}" in block
    return block


def test_music_assistant_restart_loop_uses_the_music_assistant_addon() -> None:
    block = _automation_block("restart_music_assistant_every_12_17_hours")

    for token in (
        "trigger: homeassistant",
        "event: start",
        "repeat:",
        'delay: "12:10:12"',
        "addon: d5369777_music_assistant",
        "self-rescheduling loop",
    ):
        assert token in block
