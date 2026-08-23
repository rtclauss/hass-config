from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"
SCENE_MAP_PATH = ROOT / "docs" / "inovelli_scene_actions.md"


def _automation_block(alias: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line == f"  - alias: {alias}"),
        None,
    )
    if start is None:
        raise AssertionError(f"Could not find automation alias {alias!r}")

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  - alias: ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _choose_branch(block: str, trigger_id: str) -> str:
    actions = block.split("    action:\n", 1)[1]
    marker = f"                id: {trigger_id}"
    start = actions.index(marker)
    end = actions.find("\n          - conditions:", start + len(marker))
    return actions[start:] if end == -1 else actions[start:end]


def test_laundry_double_tap_acknowledges_only_completed_washer_loads() -> None:
    block = _automation_block("laundry_switch_actions")
    branch = _choose_branch(block, "up-double")

    assert 'to: "up_double"' in block
    assert "entity_id: input_boolean.washer_reminder_active" in branch
    assert 'state: "on"' in branch
    assert "entity_id: input_select.washer_state" in branch
    for completed_state in ("CLEAN", "REMINDED", "MUSTY"):
        assert f'- "{completed_state}"' in branch
    assert "action: input_boolean.turn_off" in branch
    assert "option: IDLE" not in branch


def test_garage_double_taps_only_move_from_stable_opposite_states() -> None:
    block = _automation_block("garage_overhead_switch_actions")
    open_branch = _choose_branch(block, "up-double")
    close_branch = _choose_branch(block, "down-double")

    assert "entity_id: cover.garage_door" in open_branch
    assert 'state: "closed"' in open_branch
    assert "action: cover.open_cover" in open_branch
    assert "entity_id: cover.garage_door" in close_branch
    assert 'state: "open"' in close_branch
    assert "action: cover.close_cover" in close_branch


def test_hall_transition_double_taps_control_adaptive_path_lighting() -> None:
    block = _automation_block("hall_transition_switch_actions")
    on_branch = _choose_branch(block, "up-double")
    off_branch = _choose_branch(block, "down-double")

    assert block.count("entity_id: sensor.hall_transition_switch_action") == 2
    assert 'to: "up_double"' in block
    assert 'to: "down_double"' in block
    assert 'to: "up_single"' not in block
    assert 'to: "down_single"' not in block
    assert "action: script.adaptive_light_turn_on" in on_branch
    assert "adaptive_switch: switch.adaptive_lighting_hallway" in on_branch
    assert "- light.hall_all" in on_branch
    assert "action: light.turn_off" in off_branch
    assert "entity_id: light.hall_all" in off_branch


def test_scene_map_documents_each_switch_and_safety_contract() -> None:
    scene_map = SCENE_MAP_PATH.read_text(encoding="utf-8")

    for entity_id in (
        "sensor.laundry_wall_switch_action",
        "sensor.garage_overhead_switch_action",
        "sensor.hall_transition_switch_action",
    ):
        assert entity_id in scene_map
    assert "completed washer load" in scene_map
    assert "fully closed" in scene_map
    assert "fully open" in scene_map
    assert "Single taps remain native" in scene_map
