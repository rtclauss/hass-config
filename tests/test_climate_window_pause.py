from __future__ import annotations

import re
from pathlib import Path


CLIMATE_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"


def _automation_block(automation_id: str) -> str:
    text = CLIMATE_PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_window_climate_pause_handler_turns_off_both_thermostat_entities() -> None:
    block = _automation_block("window_climate_action_handler")

    assert "id: pause" in block
    assert "action: climate.turn_off" in block
    assert "climate.my_ecobee" in block
    assert "climate.my_ecobee_2" in block
    assert "input_boolean.window_climate_paused_by_windows" in block

    assert "input_text.set_value" not in block
    assert "window_climate_restore_preset_mode" not in block
    assert "preset_mode: away_indefinitely" not in block


def test_window_climate_resume_handler_resumes_ecobee_without_input_text_dependency() -> None:
    block = _automation_block("window_climate_action_handler")

    assert "id: resume" in block
    assert "action: ecobee.resume_program" in block
    assert "resume_all: true" in block
    assert "action: climate.turn_on" in block
    assert "input_boolean.window_climate_paused_by_windows" in block

    assert "input_text.set_value" not in block
    assert "window_climate_restore_preset_mode" not in block
