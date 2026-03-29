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


def test_tesla_departure_planner_waits_for_helpers_on_startup() -> None:
    text = _read(CAR_PATH)

    assert "id: tesla_departure_planner_apply" in text
    assert "condition: trigger\n                id: startup" in text
    assert 'delay: "00:00:30"' in text


def test_time_to_home_template_handles_unavailable_source_state() -> None:
    text = _read(TRIPS_PATH)

    assert "name: time_to_home" in text
    assert "states('sensor.me_to_home') | int(default=0)" in text
    assert "availability:" in text
    assert "'%02d:%02d:00' | format(hours, minutes)" in text


def test_bedroom_hour_of_day_remains_numeric() -> None:
    text = _read(ZIGBEE_ZWAVE_PATH)

    assert 'name: Bedroom hour of day' in text
    assert 'state: "{{ now().hour }}"' in text
    assert 'state: \'"{{ now().hour }}"\'' not in text


def test_bird_templates_guard_missing_json_fields() -> None:
    text = _read(BIRDS_PATH)

    assert "value_json is defined and value_json is mapping and value_json.common_name is defined" in text
    assert "{{ value }}" in text
    assert "value_json is defined and value_json is mapping and value_json.species is defined and value_json.species | count > 0" in text
    assert "value_json is defined and value_json is mapping and value_json.detections is defined and value_json.detections | length > 0" in text


def test_garbage_notifications_use_computed_pickup_date_sensor() -> None:
    text = _read(UTILITIES_PATH)

    assert "id: notify_garbage_day" in text
    assert "entity_id: calendar.garbage_collection" not in text
    assert "states('sensor.garbage_pickup_date')" in text
    assert 'message: DO NOT put out bins tonight. Garbage day has changed!' in text
    assert "Put out bins tonight. Garbage tomorrow." in text


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
    assert 'week_mon: "{{ base_wed - timedelta(days=base_wed.weekday()) }}"' in text
    assert "ns = namespace(hit=false)" in text
    assert "holiday_mon_to_wed in [true, 'true', 'True', 'on']" in text
    assert 'base_wednesday: "{{ base_wed.isoformat() }}"' in text
