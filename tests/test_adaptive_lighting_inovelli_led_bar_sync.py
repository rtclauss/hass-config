from __future__ import annotations

import re
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


def _script_block(script_id: str) -> str:
    lines = ADAPTIVE_LIGHTING_PATH.read_text(encoding="utf-8").splitlines()
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


def test_default_led_bar_sync_automation_updates_owner_suite_and_office() -> None:
    block = _automation_block("sync_selected_inovelli_led_bars_to_adaptive_lighting")

    assert "owner suite and office Inovelli LED bars" in block
    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert 'minutes: "/2"' in block
    assert "switch.sleep_mode" in block
    assert "input_boolean.guest_mode" in block
    assert "switch.adaptive_lighting_owner_suite" in block
    assert "switch.adaptive_lighting_sleep_mode_owner_suite" in block
    assert 'delay: "00:00:30"' in block
    assert "action: script.turn_on" in block
    assert "entity_id: script.sync_inovelli_led_bars_to_adaptive_lighting" in block
    assert "variables:" in block
    assert "action: script.sync_inovelli_led_bars_to_adaptive_lighting" not in block
    assert "- owner suite" in block
    assert "- office" in block


def test_led_bar_sync_script_accepts_room_inputs_and_maps_owner_suite_and_office() -> None:
    block = _script_block("sync_inovelli_led_bars_to_adaptive_lighting")

    assert "fields:" in block
    assert "room:" in block
    assert "rooms:" in block
    assert 'example: "owner suite, office"' in block
    assert "owner_suite:" in block
    assert "office:" in block
    assert "switch.adaptive_lighting_owner_suite" in block
    assert "switch.adaptive_lighting_office" in block
    assert "number.owner_suite_fan_switch_ledcolorwhenon" in block
    assert "number.owner_suite_fan_switch_ledintensitywhenoff" in block
    assert "number.office_fan_switch_ledcolorwhenon" in block
    assert "number.office_fan_switch_ledintensitywhenoff" in block
    assert "owner_suite_bedroom" in block


def test_led_bar_sync_script_uses_privacy_and_sleep_guards_with_office_fallback() -> None:
    block = _script_block("sync_inovelli_led_bars_to_adaptive_lighting")

    assert "entity_id: input_boolean.trip" in block
    assert 'state: "off"' in block
    assert "entity_id: switch.sleep_mode" in block
    assert "guest_mode_blocks_sync: true" in block
    assert "fallback_adaptive_switch: switch.adaptive_lighting_owner_suite" in block
    assert "light.owner_suite_lamps" in block
    assert "repeat.item == 'owner_suite'" in block
    assert "now().hour >= 22 or now().hour < 6" in block
    assert "room_specific_sync_blocked" in block
    assert "min_color_temp" in block
    assert "max_color_temp" in block
    assert "* 170" in block
    assert "value: 1" in block
