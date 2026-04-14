from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOM_INTENT_PATH = ROOT / "docs" / "room_intent.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"


def _kitchen_room_block() -> str:
    text = ROOM_INTENT_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^  kitchen:\n(?P<body>.*?)(?=^  [a-z_]+:\n|^decision_rules:\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError("Could not find kitchen block in docs/room_intent.yaml")
    return match.group(0)


def _automation_block(automation_id: str) -> str:
    text = LIGHT_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - (?:id|alias): |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in packages/light.yaml")
    return match.group(0)


def test_kitchen_room_intent_allows_motion_lighting_when_guest_mode_is_off() -> None:
    block = _kitchen_room_block()

    assert "disabled_automations" not in block
    assert "motion-activated lighting is acceptable when guest mode is off" in block
    assert "keep motion lighting practical and low-friction for food prep" in block


def test_kitchen_motion_automation_is_enabled_and_remains_restart_mode() -> None:
    block = _automation_block("kitchen_lights_toggle")

    assert "Disabled pending a new kitchen policy" not in block
    assert "initial_state: false" not in block
    assert "mode: restart" in block
    assert "binary_sensor.kitchen_motion_occupancy" in block
    assert "input_boolean.guest_mode" in block
