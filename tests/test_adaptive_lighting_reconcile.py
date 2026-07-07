from __future__ import annotations

import re
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


def _script_block(script_id: str) -> str:
    text = ADAPTIVE_LIGHTING_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  {re.escape(script_id)}:\n(.*?)(?=^  [a-zA-Z0-9_]+:\n|^switch:\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find script block {script_id!r}")
    return match.group(0)


def _adaptive_lighting_settings_block(entity_id: str) -> str:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")
    lines = block.splitlines()
    entity_line = f"          entity_id: {entity_id}"
    try:
        entity_index = lines.index(entity_line)
    except ValueError as exc:
        raise AssertionError(f"Could not find Adaptive Lighting settings for {entity_id}") from exc

    start = entity_index
    for candidate in range(entity_index, -1, -1):
        if lines[candidate] == "      - action: adaptive_lighting.change_switch_settings":
            start = candidate
            break

    end = len(lines)
    for candidate in range(entity_index + 1, len(lines)):
        if lines[candidate].startswith("      - "):
            end = candidate
            break

    return "\n".join(lines[start:end])


def test_adaptive_light_turn_on_script_wraps_atomic_adaptive_apply() -> None:
    block = _script_block("adaptive_light_turn_on")

    for token in (
        "alias: Adaptive Light Turn On",
        "mode: parallel",
        "target_lights: \"{{ lights | default([], true) }}\"",
        "member_lights: \"{{ expand(target_lights) | map(attribute='entity_id') | unique | list }}\"",
        "off_lights: \"{{ member_lights | select('is_state', 'off') | list }}\"",
        "on_lights: \"{{ member_lights | select('is_state', 'on') | list }}\"",
        "unreachable_lights: \"{{ (target_lights + member_lights) | unique | select('is_state', ['unavailable', 'unknown']) | list }}\"",
        "apply_transition: \"{{ transition | default(1, true) }}\"",
        "should_reset_manual_control: \"{{ reset_manual_control | default(false, true) }}\"",
        "should_bootstrap: \"{{ bootstrap | default(false, true) }}\"",
        "initial_brightness_pct: \"{{ bootstrap_brightness_pct | default(1, true) }}\"",
        "adaptive_switch_active: \"{{ is_state(adaptive_switch, 'on') }}\"",
        "target_color_temp_kelvin: \"{{ state_attr(adaptive_switch, 'color_temp_kelvin') | int(0) }}\"",
        'value_template: "{{ should_reset_manual_control and adaptive_switch_active and member_lights | count > 0 }}"',
        'lights: "{{ member_lights }}"',
        "value_template: \"{{ not adaptive_switch_active and target_lights | count > 0 }}\"",
        "value_template: \"{{ adaptive_switch_active and target_lights | count == 0 }}\"",
        "value_template: \"{{ should_bootstrap and target_color_temp_kelvin > 0 and off_lights | count > 0 }}\"",
        'value_template: "{{ not should_reset_manual_control }}"',
        "value_template: \"{{ off_lights | count > 0 or on_lights | count > 0 }}\"",
        "value_template: \"{{ adaptive_switch_active and unreachable_lights | count > 0 }}\"",
        "action: light.turn_on",
        "continue_on_error: true",
        'for_each: "{{ off_lights }}"',
        'entity_id: "{{ repeat.item }}"',
        'entity_id: "{{ unreachable_lights }}"',
        'brightness_pct: "{{ initial_brightness_pct }}"',
        "state_attr(repeat.item, 'min_color_temp_kelvin')",
        "state_attr(repeat.item, 'max_color_temp_kelvin')",
        "transition: 0",
        "action: adaptive_lighting.apply",
        'entity_id: "{{ adaptive_switch }}"',
        'lights: "{{ off_lights }}"',
        'value_template: "{{ on_lights | count > 0 }}"',
        'lights: "{{ on_lights }}"',
        'lights: "{{ off_lights + on_lights }}"',
        "adapt_brightness: true",
        "adapt_color: false",
        "adapt_color: true",
        "turn_on_lights: true",
        'transition: "{{ apply_transition }}"',
        "manual_control: true",
        'value_template: "{{ clear_candidates | count > 0 }}"',
        "entity_id: script.adaptive_light_clear_manual_control",
        'clear_lights: "{{ clear_candidates }}"',
        'wait_seconds: "{{ apply_transition | float(0) }}"',
    ):
        assert token in block

    # The off lights are pre-marked as manually controlled before the
    # bootstrap turn-on so the Adaptive Lighting interceptor passes it
    # through unmodified for every switch configuration.
    mark_index = block.index("manual_control: true")
    bootstrap_index = block.index('brightness_pct: "{{ initial_brightness_pct }}"')
    assert mark_index < bootstrap_index

    # Reset/ramp callers such as the owner-suite wake sequence still lock
    # manual control even when the visible bootstrap pulse is disabled.
    reset_lock_index = block.index(
        'value_template: "{{ should_reset_manual_control and adaptive_switch_active '
        'and member_lights | count > 0 }}"'
    )
    first_apply_index = block.index("action: adaptive_lighting.apply")
    assert reset_lock_index < first_apply_index

    # Immediate (pre-ramp) clears must not exist in the turn-on script:
    # clearing manual control force-adapts at the switch's initial_transition
    # and would stomp the ramp. The clear is deferred to the fire-and-forget
    # helper so callers are not blocked for the ramp duration either.
    assert "manual_control: false" not in block
    assert block.rindex("action: adaptive_lighting.apply") < block.index(
        "entity_id: script.adaptive_light_clear_manual_control"
    )


def test_adaptive_light_bootstrap_only_enabled_for_kitchen_and_basement() -> None:
    allowed_switches = {
        "switch.adaptive_lighting_kitchen",
        "switch.adaptive_lighting_basement",
    }
    for path in (
        ADAPTIVE_LIGHTING_PATH.parents[1] / "packages" / "light.yaml",
        ADAPTIVE_LIGHTING_PATH.parents[1] / "packages" / "zigbee_zwave.yaml",
    ):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "bootstrap: true":
                continue

            preceding = "\n".join(lines[max(0, index - 8) : index + 1])
            matching_switches = {
                switch for switch in allowed_switches if f"adaptive_switch: {switch}" in preceding
            }
            assert matching_switches, (
                f"{path.name}:{index + 1} enables adaptive_light_turn_on bootstrap "
                "outside the kitchen/basement allow-list"
            )


def test_adaptive_light_clear_manual_control_waits_and_guards() -> None:
    block = _script_block("adaptive_light_clear_manual_control")

    for token in (
        "alias: Adaptive Light Clear Manual Control",
        "mode: parallel",
        'seconds: "{{ wait_seconds | float(0) }}"',
        "is_state(light_id, 'on')",
        "state_attr(light_id, 'brightness')",
        "state_attr(light_id, 'supported_color_modes')",
        "state_attr(light_id, 'color_temp_kelvin')",
        "state_attr(light_id, 'min_color_temp_kelvin')",
        "state_attr(light_id, 'max_color_temp_kelvin')",
        "brightness_ok and color_ok",
        'value_template: "{{ lights_to_clear | count > 0 }}"',
        'lights: "{{ lights_to_clear }}"',
        "action: adaptive_lighting.set_manual_control",
        "manual_control: false",
    ):
        assert token in block

    # The ramp wait comes before the guard evaluation and the single clear.
    delay_index = block.index('seconds: "{{ wait_seconds | float(0) }}"')
    guard_index = block.index("is_state(light_id, 'on')")
    clear_index = block.index("manual_control: false")
    assert delay_index < guard_index < clear_index
    assert block.count("manual_control: false") == 1


def test_owner_suite_adaptive_lighting_reconciles_supported_scene_safe_settings() -> None:
    block = _automation_block("reconcile_owner_suite_adaptive_lighting")

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert 'delay: "00:00:30"' in block
    assert "action: adaptive_lighting.change_switch_settings" in block
    assert "kitchen, den, basement, dining-room, owner-suite, and vanity tuning survive" in block
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


def test_owner_suite_vanity_adaptive_lighting_reconciles_scene_safe_baseline() -> None:
    settings = _adaptive_lighting_settings_block("switch.adaptive_lighting_owner_suite_vanity")

    for token in (
        "use_defaults: current",
        "include_config_in_attributes: true",
        "take_over_control: true",
        "adapt_only_on_bare_turn_on: true",
        "only_once: true",
        "initial_transition: 1",
        "sleep_transition: 2",
        "transition: 5",
        "sleep_brightness: 1",
        "sleep_color_temp: 1000",
        "detect_non_ha_changes: false",
    ):
        assert token in settings


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
        "arrival_common_adaptive_switches:",
        "arrival_owner_suite_adaptive_switches:",
        "arrival_adaptive_switches:",
        "arrival_enabled_adaptive_switches:",
        "switch.adaptive_lighting_kitchen",
        "switch.adaptive_lighting_den",
        "switch.adaptive_lighting_hallway",
        "switch.adaptive_lighting_owner_suite",
        "if is_state('binary_sensor.bayesian_bed_occupancy', 'off')",
        "is_state(adaptive_switch, 'on')",
        "turn_on_lights: false",
    ):
        assert token in block

    empty_house_branch = block.split(
        'alias: "Apply globally when this arrival starts from an empty house"', maxsplit=1
    )[1].split("default:", maxsplit=1)[0]
    assert "arrival_home_was_empty and arrival_enabled_adaptive_switches | count > 0" in empty_house_branch
    assert "entity_id: \"{{ arrival_enabled_adaptive_switches }}\"" in empty_house_branch
    assert not any(line.strip() == "lights:" for line in empty_house_branch.splitlines())

    occupied_house_branch = block.split("default:", maxsplit=1)[1]
    for token in (
        'for_each: "{{ arrival_enabled_adaptive_switches }}"',
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
        "Dining room remains out of scope",
        "If bed_occupied is true",
        "arrival never re-enables a",
        "manual_control attribute",
        "rule PreserveManualLightingDuringOccupiedArrival",
        "requires: not arrival.home_was_empty_before_arrival",
        "ManualControlledArrivalLightsPreserved",
        "configured lights minus the current manual_control list",
    ):
        assert token in text
