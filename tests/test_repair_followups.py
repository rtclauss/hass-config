from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PATH = ROOT / "packages" / "car.yaml"
CLIMATE_PATH = ROOT / "packages" / "climate.yaml"
IOS_WAKEUP_PATH = ROOT / "packages" / "ios_wakeup.yaml"
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"


def _automation_block(path: Path, automation_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")
    return match.group(0)


def test_window_climate_actions_do_not_depend_on_restore_preset_input_text() -> None:
    package = CLIMATE_PATH.read_text(encoding="utf-8")
    block = _automation_block(CLIMATE_PATH, "window_climate_action_handler")

    assert "window_climate_restore_preset_mode" not in package
    assert "input_text.set_value" not in block
    assert "climate.turn_off" in block
    assert "climate.turn_on" in block
    assert "ecobee.resume_program" in block


def test_ios_wakeup_sync_skips_diagnostic_input_text_write() -> None:
    package = IOS_WAKEUP_PATH.read_text(encoding="utf-8")
    block = _automation_block(IOS_WAKEUP_PATH, "sync_phone_wakeup_alarm_from_ios_shortcut")

    assert "input_text.phone_wakeup_alarm_time" not in package
    assert "input_text.set_value" not in block
    assert "script.set_wakeup_from_phone_alarm" in block


def test_tesla_planner_tracks_managed_departures_without_input_text_service() -> None:
    package = CAR_PATH.read_text(encoding="utf-8")
    planner_block = _automation_block(CAR_PATH, "tesla_departure_planner_apply")
    cleanup_block = _automation_block(CAR_PATH, "tesla_departure_schedule_cleanup")

    assert "input_text.tesla_managed_departure_time" not in package
    assert "input_datetime.tesla_managed_departure_time" not in package
    assert "input_number.tesla_managed_departure_ts" in package
    assert "input_boolean.tesla_managed_departure_active" in package
    assert "input_number.set_value" in planner_block
    assert "input_boolean.turn_on" in planner_block
    assert "input_boolean.turn_off" in planner_block
    assert "input_number.set_value" in cleanup_block
    assert "input_boolean.turn_off" in cleanup_block


def test_switch_action_automations_use_current_live_light_entities() -> None:
    package = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    for stale_entity_id in (
        "light.dining_room_overhead",
        "light.kitchen_overhead",
    ):
        assert stale_entity_id not in package

    assert "light.dining_room_all" in package
    assert "light.kitchen_all" in package
