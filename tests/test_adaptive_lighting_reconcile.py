from __future__ import annotations

from pathlib import Path


ADAPTIVE_LIGHTING_PATH = (
    Path(__file__).resolve().parents[1] / "packages" / "adaptive_lighting.yaml"
)


def _automation_block(automation_id: str) -> str:
    lines = ADAPTIVE_LIGHTING_PATH.read_text(encoding="utf-8").splitlines()
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


def test_owner_suite_adaptive_lighting_reconciles_supported_scene_safe_settings() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert 'delay: "00:00:30"' in block
    assert "action: adaptive_lighting.change_switch_settings" in block
    assert "scene-friendly Adaptive Lighting baselines" in block
    assert "entity_id: switch.adaptive_lighting_owner_suite" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: true" in block
    assert "adapt_only_on_bare_turn_on: true" in block
    assert "only_once: true" in block
    assert "initial_transition: 2" in block
    assert "transition: 5" in block
    assert "detect_non_ha_changes: false" in block


def test_dining_room_adaptive_lighting_reconciles_legacy_switch_to_scene_safe_settings() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert 'delay: "00:00:30"' in block
    assert "legacy living-room suffix" in block
    assert "action: adaptive_lighting.change_switch_settings" in block
    assert "entity_id: switch.dining_room_adaptive_lighting_living_room" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: true" in block
    assert "adapt_only_on_bare_turn_on: true" in block
    assert "only_once: true" in block
    assert "initial_transition: 1" in block
    assert "transition: 5" in block
    assert "detect_non_ha_changes: false" in block
