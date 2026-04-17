from __future__ import annotations

from pathlib import Path


ADAPTIVE_LIGHTING_PATH = (
    Path(__file__).resolve().parents[1] / "packages" / "adaptive_lighting.yaml"
)
ARRIVAL_LIGHTING_SPEC_PATH = (
    Path(__file__).resolve().parents[1] / "specs" / "arrival_lighting.allium"
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
    assert "kitchen, den, basement, dining-room, and owner-suite tuning survive restarts" in block
    assert "entity_id: switch.adaptive_lighting_owner_suite" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: true" in block
    assert "adapt_only_on_bare_turn_on: true" in block
    assert "only_once: false" in block
    assert "initial_transition: 2" in block
    assert "sleep_transition: 2" in block
    assert "transition: 5" in block
    assert "sleep_brightness: 1" in block
    assert "sleep_color_temp: 1000" in block
    assert "detect_non_ha_changes: false" in block
    assert "event: adaptive_lighting_startup_reconciled" in block


def test_dining_room_adaptive_lighting_reconciles_current_switch_to_scene_safe_settings() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert 'delay: "00:00:30"' in block
    assert "current dining-room entity id" in block
    assert "action: adaptive_lighting.change_switch_settings" in block
    assert "entity_id: switch.dining_room_adaptive_lighting_dining_room" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: true" in block
    assert "adapt_only_on_bare_turn_on: true" in block
    assert "only_once: true" in block
    assert "initial_transition: 1" in block
    assert "transition: 5" in block
    assert "detect_non_ha_changes: false" in block


def test_kitchen_adaptive_lighting_reconciles_bright_scene_safe_settings() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "preserving each room's intended scene and task-lighting behavior" in block
    assert "action: adaptive_lighting.change_switch_settings" in block
    assert "entity_id: switch.adaptive_lighting_kitchen" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: true" in block
    assert "adapt_only_on_bare_turn_on: true" in block
    assert "only_once: true" in block
    assert "initial_transition: 1" in block
    assert "transition: 3" in block
    assert "detect_non_ha_changes: false" in block


def test_den_adaptive_lighting_reconciles_scene_safe_settings_for_media_use() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "action: adaptive_lighting.change_switch_settings" in block
    assert "entity_id: switch.adaptive_lighting_den" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: true" in block
    assert "adapt_only_on_bare_turn_on: true" in block
    assert "only_once: true" in block
    assert "initial_transition: 2" in block
    assert "transition: 2" in block
    assert "separate_turn_on_commands: true" in block
    assert "detect_non_ha_changes: false" in block


def test_basement_adaptive_lighting_reconciles_live_media_safe_settings() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "entity_id: switch.adaptive_lighting_basement" in block
    assert "use_defaults: current" in block
    assert "include_config_in_attributes: true" in block
    assert "take_over_control: false" in block
    assert "adapt_only_on_bare_turn_on: false" in block
    assert "only_once: false" in block
    assert "initial_transition: 0" in block
    assert "sleep_transition: 1" in block
    assert "transition: 5" in block
    assert "min_brightness: 25" in block
    assert "max_brightness: 100" in block
    assert "min_color_temp: 2000" in block
    assert "max_color_temp: 5500" in block
    assert "sleep_brightness: 1" in block
    assert "sleep_color_temp: 1000" in block
    assert "detect_non_ha_changes: false" in block


def test_arrival_adaptive_lighting_scopes_occupied_arrivals_to_non_manual_lights() -> None:
    block = _automation_block("apply_adaptive_lighting_on_arrival")

    for token in (
        "id: bayesian-device-entered-home",
        "id: bayesian-presence-turned-on",
        "arrival_home_was_empty",
        "trigger.from_state.state == 'off'",
        "is_state('binary_sensor.bayesian_zeke_home', 'off')",
        "arrival_adaptive_switches:",
        "switch.adaptive_lighting_kitchen",
        "switch.adaptive_lighting_den",
        "switch.adaptive_lighting_hallway",
        "switch.adaptive_lighting_owner_suite",
        "turn_on_lights: false",
    ):
        assert token in block

    empty_house_branch = block.split(
        'alias: "Apply globally when this arrival starts from an empty house"', maxsplit=1
    )[1].split("default:", maxsplit=1)[0]
    assert "entity_id: \"{{ arrival_adaptive_switches }}\"" in empty_house_branch
    assert not any(line.strip() == "lights:" for line in empty_house_branch.splitlines())

    occupied_house_branch = block.split("default:", maxsplit=1)[1]
    for token in (
        'for_each: "{{ arrival_adaptive_switches }}"',
        "state_attr(repeat.item, 'configuration') or {}",
        "manual_controlled_lights",
        "state_attr(repeat.item, 'manual_control') or []",
        "reject('in', manual_controlled_lights)",
        "eligible_arrival_lights | count > 0",
        "entity_id: \"{{ repeat.item }}\"",
        "lights: \"{{ eligible_arrival_lights }}\"",
    ):
        assert token in occupied_house_branch


def test_arrival_lighting_spec_documents_empty_house_and_manual_control_gates() -> None:
    text = ARRIVAL_LIGHTING_SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "home_was_empty_before_arrival: Boolean",
        "If the house was empty before this arrival",
        "If someone was already home",
        "manual_control attribute",
        "rule PreserveManualLightingDuringOccupiedArrival",
        "requires: not arrival.home_was_empty_before_arrival",
        "ManualControlledArrivalLightsPreserved",
        "configured lights minus the current manual_control list",
    ):
        assert token in text
