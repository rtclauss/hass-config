from __future__ import annotations

from pathlib import Path


HOLIDAYS_PATH = Path(__file__).resolve().parents[1] / "packages" / "holidays.yaml"


def _automation_block(automation_id: str) -> str:
    lines = HOLIDAYS_PATH.read_text(encoding="utf-8").splitlines()
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


def test_single_outdoor_holiday_loop_replaces_legacy_holiday_loop_automations() -> None:
    text = HOLIDAYS_PATH.read_text(encoding="utf-8")

    assert "- id: outdoor_holiday_light_loop" in text
    assert "- id: christmas_outside_light_loop_1" not in text
    assert "- id: st_andrews_day_light_loop" not in text
    assert "- id: halloween_light_loop" not in text


def test_outdoor_holiday_loop_uses_active_outdoor_holiday_selector_and_script() -> None:
    block = _automation_block("outdoor_holiday_light_loop")

    assert 'minutes: "/1"' in block
    assert "states('sensor.active_outdoor_holiday') | trim" in block
    assert "action: script.apply_outdoor_holiday_scene" in block
    assert 'holiday_key: "{{ states(\'sensor.active_outdoor_holiday\') | trim }}"' in block


def test_christmas_toggle_only_manages_tree_automations() -> None:
    block = _automation_block("toggle_christmas_automations_on_season_change")

    assert "automation.christmas_tree_on" in block
    assert "automation.christmas_tree_off_midnight" in block
    assert "automation.christmas_lights_off_bedroom_off" in block
    assert "automation.christmas_outside_light_loop_1" not in block
