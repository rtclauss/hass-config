from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESK_PACKAGE = ROOT / "packages" / "desk.yaml"
OFFICE_TILE = ROOT / "lovelace" / "tiles" / "tiles_office.yaml"
MUSHROOM_DASHBOARD = ROOT / ".storage" / "lovelace.ryan_new_mushroom"

NATIVE_DESK_BUTTONS = {
    "button.uplift_desk_75b205_move_to_max_height",
    "button.uplift_desk_75b205_move_to_min_height",
    "button.uplift_desk_75b205_move_to_preset_1",
    "button.uplift_desk_75b205_move_to_preset_2",
    "button.uplift_desk_75b205_stop",
}

MANUAL_DESK_SCRIPTS = {
    "script.uplift_desk_manual_move_max",
    "script.uplift_desk_manual_move_min",
    "script.uplift_desk_manual_move_preset_1",
    "script.uplift_desk_manual_move_preset_2",
    "script.uplift_desk_manual_stop",
}

AUTO_DESK_WRAPPERS = {
    "uplift_desk_auto_move_max": "button.uplift_desk_75b205_move_to_max_height",
    "uplift_desk_auto_move_preset_1": "button.uplift_desk_75b205_move_to_preset_1",
    "uplift_desk_auto_move_preset_2": "button.uplift_desk_75b205_move_to_preset_2",
}


def _script_block(script_id: str) -> str:
    lines = DESK_PACKAGE.read_text(encoding="utf-8").splitlines()
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


def test_desk_package_uses_native_uplift_component_buttons() -> None:
    text = DESK_PACKAGE.read_text(encoding="utf-8")

    for entity_id in NATIVE_DESK_BUTTONS:
        assert entity_id in text

    assert "shell_command.uplift_desk" not in text
    assert "uplift_ble_remote.sh" not in text


def test_office_dashboards_use_manual_desk_script_wrappers() -> None:
    for path in (OFFICE_TILE, MUSHROOM_DASHBOARD):
        text = path.read_text(encoding="utf-8")

        for entity_id in MANUAL_DESK_SCRIPTS:
            assert entity_id in text

        assert "service: button.press" not in text
        assert '"service": "button.press"' not in text
        assert "button.uplift_desk_75b205_move_to_" not in text
        assert "button.uplift_desk_75b205_stop" not in text


def test_auto_desk_wrappers_share_motion_guard() -> None:
    shared = _script_block("uplift_desk_auto_move")

    assert "entity_id: timer.uplift_desk_motion_window" in shared
    assert 'state: "idle"' in shared
    assert "action: button.press" in shared
    assert 'entity_id: "{{ target_button }}"' in shared
    assert "action: timer.start" in shared
    assert shared.count("timer.uplift_desk_motion_window") == 2

    for script_id, target_button in AUTO_DESK_WRAPPERS.items():
        block = _script_block(script_id)

        assert "action: script.uplift_desk_auto_move" in block
        assert f"target_button: {target_button}" in block
        assert "timer.uplift_desk_motion_window" not in block
        assert "action: button.press" not in block
