from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIGHT_PATH = ROOT / "packages" / "light.yaml"


def _automation_block(automation_id: str) -> str:
    text = LIGHT_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - (?:id|alias): {re.escape(automation_id)}\n(.*?)(?=^  - (?:id|alias): |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_front_door_entry_path_uses_contact_and_mmwave_vacancy() -> None:
    block = _automation_block("front_door_light_auto_toggle")

    assert "id: front-door-opened" in block
    assert "id: front-path-vacant" in block
    assert "binary_sensor.main_foyer_front_door_contact" in block
    for entity_id in (
        "binary_sensor.hall_transition_switch_occupancy",
        "binary_sensor.hall_transition_switch_area1occupancy",
        "binary_sensor.hall_transition_switch_area2occupancy",
    ):
        assert entity_id in block
    assert "minutes: 2" in block


def test_front_door_entry_path_is_targeted_and_preserves_manual_offs() -> None:
    block = _automation_block("front_door_light_auto_toggle")

    assert "light.hall_foyer_switch" in block
    assert "light.hall_transition_switch" in block
    assert "light.hall_all" not in block
    assert "brightness_pct: 20" in block
    assert 'after: "23:00:00"' in block
    assert 'before: "06:00:00"' in block
    assert "input_boolean.front_door_auto_on" in block
    assert "action: input_boolean.turn_off" in block


def test_garage_entry_path_uses_contact_mmwave_and_auto_on_guard() -> None:
    block = _automation_block("garage_entry_door_light_auto_toggle")

    assert "id: garage-door-opened" in block
    assert "id: garage-path-vacant" in block
    assert "binary_sensor.hall_garage_entry_contact" in block
    for entity_id in (
        "binary_sensor.hall_transition_switch_occupancy",
        "binary_sensor.hall_transition_switch_area1occupancy",
        "binary_sensor.hall_transition_switch_area2occupancy",
    ):
        assert entity_id in block
    assert "input_boolean.garage_entry_auto_on" in block
    assert "brightness_pct: 15" in block
    assert "brightness_pct: 75" in block


def test_garage_entry_path_targets_garage_side_lights_only() -> None:
    block = _automation_block("garage_entry_door_light_auto_toggle")

    assert "light.hall_transition_switch" in block
    assert "light.hall_garage_laundry_switch" in block
    assert "light.garage_overhead_switch" in block
    assert "light.hall_foyer_switch" not in block
    assert "light.hall_all" not in block


def test_hallway_pass_through_uses_transition_mmwave_occupancy() -> None:
    for automation_id in ("hallway_light_toggle_at_night", "toggle_hallway_day"):
        block = _automation_block(automation_id)
        assert block.count("binary_sensor.hall_transition_switch_occupancy") >= 4
        assert "id: main-motion-sensed" in block
        assert "id: main-motion-not-detected" in block
