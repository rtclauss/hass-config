from __future__ import annotations

import re
from pathlib import Path


DESK_PATH = Path(__file__).resolve().parents[1] / "packages" / "desk.yaml"


def _script_block(script_id: str) -> str:
    lines = DESK_PATH.read_text(encoding="utf-8").splitlines()
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


def test_automatic_desk_moves_skip_unavailable_buttons() -> None:
    expectations = {
        "uplift_desk_auto_move_max": "button.uplift_desk_75b205_move_to_max_height",
        "uplift_desk_auto_move_preset_1": "button.uplift_desk_75b205_move_to_preset_1",
        "uplift_desk_auto_move_preset_2": "button.uplift_desk_75b205_move_to_preset_2",
    }

    for script_id, button_id in expectations.items():
        block = _script_block(script_id)

        assert 'entity_id: timer.uplift_desk_motion_window' in block
        assert 'state: "idle"' in block
        assert block.count(f"entity_id: {button_id}") >= 3
        assert 'state: "unavailable"' in block
        assert 'state: "unknown"' in block
        assert "action: timer.start" in block


def test_manual_desk_moves_skip_unavailable_buttons() -> None:
    expectations = {
        "uplift_desk_manual_move_max": "button.uplift_desk_75b205_move_to_max_height",
        "uplift_desk_manual_move_preset_1": "button.uplift_desk_75b205_move_to_preset_1",
        "uplift_desk_manual_move_preset_2": "button.uplift_desk_75b205_move_to_preset_2",
    }

    for script_id, button_id in expectations.items():
        block = _script_block(script_id)

        assert block.count(f"entity_id: {button_id}") >= 3
        assert 'state: "unavailable"' in block
        assert 'state: "unknown"' in block
        assert "action: button.press" in block
