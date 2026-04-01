from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLEANING_PATH = ROOT / "packages" / "cleaning.yaml"
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
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
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def _template_binary_sensor_block(unique_id: str) -> str:
    lines = CLEANING_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line != f"        unique_id: {unique_id}":
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("      - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find template binary sensor {unique_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("      - ") or lines[index].startswith("  - trigger:"):
            end = index
            break

    return "\n".join(lines[start:end])


def test_cleaning_package_uses_smart_plug_power_for_laundry_running_detection() -> None:
    washer_block = _template_binary_sensor_block("washing_machine_running")
    dryer_block = _template_binary_sensor_block("dryer_running")

    assert "delay_on: 0:01:00" in washer_block
    assert "delay_off: 0:08:00" in washer_block
    assert "sensor.laundry_room_washing_machine_power" in washer_block
    assert "| float(0) > 8" in washer_block
    assert "is_state('binary_sensor.washer'" not in washer_block

    assert "delay_on: 0:02:00" in dryer_block
    assert "delay_off: 0:03:00" in dryer_block
    assert "sensor.laundry_room_dryer_power" in dryer_block
    assert "| float(0) > 75" in dryer_block
    assert "is_state('binary_sensor.dryer'" not in dryer_block


def test_cleaning_package_notifies_from_power_based_running_sensors() -> None:
    washer_started = _automation_block(CLEANING_PATH, "washer_started")
    wash_finished = _automation_block(CLEANING_PATH, "wash_finished")
    dryer_finished = _automation_block(CLEANING_PATH, "dryer_finished")
    washer_reminder = _automation_block(CLEANING_PATH, "washer_reminder")
    washer_cleared = _automation_block(CLEANING_PATH, "washer_cleared")

    assert "entity_id: binary_sensor.washing_machine_running" in washer_started
    assert 'from: "off"' in washer_started
    assert 'to: "on"' in washer_started
    assert "input_boolean.washer_wet_load_pending" in washer_started
    assert "option: CLEANING" in washer_started

    assert "entity_id: binary_sensor.washing_machine_running" in wash_finished
    assert 'from: "on"' in wash_finished
    assert 'to: "off"' in wash_finished
    assert "input_datetime.washer_finished_at" in wash_finished
    assert "input_boolean.washer_wet_load_pending" in wash_finished
    assert "option: CLEAN" in wash_finished
    assert "binary_sensor.front_load_washer_wash_completed" not in wash_finished

    assert "entity_id: binary_sensor.dryer_running" in dryer_finished
    assert 'from: "on"' in dryer_finished
    assert 'to: "off"' in dryer_finished
    assert 'message: "Dryer finished!' in dryer_finished

    assert 'trigger: time_pattern' in washer_reminder
    assert 'minutes: "/10"' in washer_reminder
    assert 'trigger: homeassistant' in washer_reminder
    assert "input_boolean.washer_wet_load_pending" in washer_reminder
    assert "binary_sensor.laundry_room_washing_machine_door_contact" in washer_reminder
    assert "input_datetime.washer_finished_at" in washer_reminder
    assert "18 * 60 * 60" in washer_reminder
    assert "option: MUSTY" in washer_reminder
    assert "binary_sensor.front_load_washer_wash_completed" not in washer_reminder

    assert "binary_sensor.laundry_room_washing_machine_door_contact" in washer_cleared
    assert 'to: "on"' in washer_cleared
    assert "input_boolean.washer_wet_load_pending" in washer_cleared
    assert "option: IDLE" in washer_cleared


def test_cleaning_package_tracks_wet_load_helpers() -> None:
    config = CLEANING_PATH.read_text(encoding="utf-8")

    assert "washer_wet_load_pending:" in config
    assert "input_datetime:" in config
    assert "washer_finished_at:" in config
    assert "binary_sensor.laundry_room_washing_machine_door_contact:" in config
    assert "input_select.washer_state:" in config


def test_utilities_package_keeps_laundry_plugs_powered() -> None:
    block = _automation_block(UTILITIES_PATH, "turn_laundry_plugs_back_on")

    assert "switch.laundry_room_washing_machine" in block
    assert "switch.laundry_room_dryer" in block
    assert 'to: "off"' in block
    assert 'event: start' in block
    assert "- action: switch.turn_on" in block
