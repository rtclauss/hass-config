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


def test_house_transition_no_longer_queues_later_mode_changes() -> None:
    text = _script_block("house_transition")

    assert "house_transition:" in text
    assert "mode: restart" in text
    assert "script.lights_off_except" in text


def test_departure_vacuum_publish_runs_in_parallel_with_house_transition() -> None:
    text = ZONE_PATH.read_text(encoding="utf-8")

    assert "parallel:" in text
    assert "action: script.house_transition" in text
    assert "action: mqtt.publish" in text
