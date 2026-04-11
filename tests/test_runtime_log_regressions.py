from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PATH = ROOT / "packages" / "car.yaml"
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"
BIRDS_PATH = ROOT / "packages" / "birds.yaml"
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"
HOLIDAYS_PATH = ROOT / "packages" / "holidays.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def test_tesla_departure_planner_waits_for_helpers_on_startup() -> None:
    text = _read(CAR_PATH)

    assert "id: tesla_departure_planner_apply" in text
    assert "condition: trigger\n                id: startup" in text
    assert 'delay: "00:00:30"' in text


def test_tesla_departure_planner_notification_uses_notify_all_with_error_tolerance() -> None:
    text = _read(CAR_PATH)

    assert "id: tesla_departure_planner_apply" in text
    assert "continue_on_error: true" in text
    assert "action: notify.notify_all" in text


def test_time_to_home_template_handles_unavailable_source_state() -> None:
    text = _read(TRIPS_PATH)

    assert "name: time_to_home" in text
    assert "states('sensor.me_to_home') | int(default=0)" in text
    assert "availability:" in text
    assert "'%02d:%02d:00' | format(hours, minutes)" in text


def test_trip_templates_treat_minnesota_as_home_destination() -> None:
    text = _read(TRIPS_PATH)

    assert '"MINNESOTA"' in text
    assert 'destination_code not in ["", "MSP", "RST", "MINNEAPOLIS", "MINNEAPOLISSTPAUL", "ROCHESTER", "MINNESOTA"]' in text
    assert "{% set home_codes = ['MSP', 'RST', 'MINNEAPOLIS', 'MINNEAPOLISSTPAUL', 'ROCHESTER', 'MINNESOTA'] %}" in text

def test_trip_mode_manager_can_enable_trip_mode_when_departing_for_scheduled_travel() -> None:
    block = _automation_block(TRIPS_PATH, "trip_mode_manager")

    assert "id: depart_for_scheduled_trip" in block
    assert "trigger.id != 'depart_for_scheduled_trip'" in block
    assert "entity_id: binary_sensor.planned_work_trip_calendar" in block
    assert "sensor.ecobee_calendar_vacation_schedule" in block
    assert "start_ts - 21600" in block


def test_bedroom_hour_of_day_remains_numeric() -> None:
    text = _read(ZIGBEE_ZWAVE_PATH)

    assert 'name: Bedroom hour of day' in text
    assert 'state: "{{ now().hour }}"' in text
    assert 'state: \'"{{ now().hour }}"\'' not in text


def test_bird_templates_guard_missing_json_fields() -> None:
    text = _read(BIRDS_PATH)

    assert "{% set raw_value = value | default('', true) | trim %}" in text
    assert "{% set raw_json = raw_value | replace('&#34;', '\"') | replace('&quot;', '\"') %}" in text
    assert "{% set payload = raw_json | from_json(default={}) %}" in text
    assert "payload is mapping and payload.common_name is defined" in text
    assert "value_json is defined and value_json is mapping and value_json.species is defined and value_json.species | count > 0" in text
    assert "value_json is defined and value_json is mapping and value_json.detections is defined and value_json.detections | length > 0" in text


def test_garbage_notifications_use_computed_pickup_date_sensor() -> None:
    text = _read(UTILITIES_PATH)

    assert "id: notify_garbage_day" in text
    assert "entity_id: calendar.garbage_collection" not in text
    assert "states('sensor.garbage_pickup_date')" in text
    assert 'message: DO NOT put out bins tonight. Garbage day has changed!' in text
    assert "Put out bins tonight. Garbage tomorrow." in text


def test_stale_entity_notification_only_exists_when_entities_are_present() -> None:
    block = _automation_block(UTILITIES_PATH, "check_non_responding_entities")

    assert "stale_threshold_hours: 12" in block
    assert "stale_entities:" in block
    assert "last_reported" in block
    assert "persistent_notification.create" in block
    assert "persistent_notification.dismiss" in block
    assert "notification_id: stale-entities" in block
    assert "stale_entities | trim != ''" in block
    assert "have not reported in {{ stale_threshold_hours }} hours" in block
    assert "have not updated in 24 hours" not in block


def test_house_electrical_meter_never_emits_literal_unavailable() -> None:
    text = _read(UTILITIES_PATH)

    assert "name: house_electrical_meter" in text
    assert "{{ none }}" in text
    assert "unavailable\n" not in text.split("name: house_electrical_meter", 1)[1].split("name: house_electrical_meter_non_ev", 1)[0]


def test_garbage_pickup_template_keeps_dates_serializable() -> None:
    text = _read(HOLIDAYS_PATH)

    assert "garbage_pickup_window_json" not in text
    assert "garbage_pickup_window.range_start" not in text
    assert 'start_date_time: "{{ range_start }}"' in text
    assert 'end_date_time: "{{ range_end }}"' in text
    assert 'today: "{{ now().date().isoformat() }}"' in text
    assert 'today_weekday: "{{ now().weekday() }}"' in text
    assert "today.weekday()" not in text
    assert "week_mon.isoformat()" not in text
    assert "base_wed.isoformat()" not in text
    assert "strptime(base_wed, '%Y-%m-%d').date()" in text
    assert "ns = namespace(hit=false)" in text
    assert "holiday_mon_to_wed in [true, 'true', 'True', 'on']" in text
    assert 'base_wednesday: "{{ base_wed }}"' in text


def test_front_door_lock_template_has_backing_helper() -> None:
    text = _read(ZIGBEE_ZWAVE_PATH)

    input_boolean_block = text.split("input_boolean:\n", 1)[1].split(
        "\n########################\n# Input Numbers", 1
    )[0]

    assert "front_door_lock:" in input_boolean_block
    assert "unique_id: front_door_lock_template" in text
    assert "entity_id:\n                - input_boolean.front_door_lock" in text


def test_owner_suite_led_shutdown_waits_for_inovelli_state_settle() -> None:
    text = _read(ZIGBEE_ZWAVE_PATH)

    block = text.split("turn_off_owner_suite_inovelli_switch_leds:\n", 1)[1].split(
        "\n########################\n# REST Command",
        1,
    )[0]

    assert "initial_grace_period: 30" in block
    assert "expected_state: 0" in block
    assert block.count("action: number.set_value") == 3


def test_lights_off_except_only_targets_currently_on_lights() -> None:
    text = _read(ROOT / "packages" / "light.yaml")

    block = text.split("lights_off_except:\n", 1)[1].split(
        "\n########################\n# Sensor",
        1,
    )[0]

    assert "selectattr('state', 'eq', 'on')" in block
    assert "rejectattr('state','in','off')" not in block


def test_lights_off_except_skips_light_groups_that_contain_protected_members() -> None:
    text = _read(ROOT / "packages" / "light.yaml")

    block = text.split("lights_off_except:\n", 1)[1].split(
        "\n########################\n# Sensor",
        1,
    )[0]

    assert "protected_lights:" in block
    assert "state_attr(light.entity_id, 'entity_id')" in block
    assert "members | select('in', excluded)" in block
    assert "rejectattr('entity_id', 'in', protected_lights)" in block
