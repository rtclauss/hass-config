from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PACKAGE_PATH = ROOT / "packages" / "car.yaml"
TESLA_TILE_PATH = ROOT / "lovelace" / "tiles" / "tiles_tesla_charging.yaml"
DASHBOARD_PATH = ROOT / ".storage" / "lovelace.ryan_new_mushroom"


def test_daily_plan_binary_sensor_tracks_inverse_of_max_range_override() -> None:
    package_text = CAR_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "default_entity_id: binary_sensor.tesla_daily_plan_active" in package_text
    assert "unique_id: tesla_daily_plan_active" in package_text
    assert "name: Tesla Daily Plan Active" in package_text
    assert "{{ is_state('input_boolean.long_range_travel', 'off') }}" in package_text


def test_yaml_dashboard_uses_inverse_sensor_for_daily_plan_button() -> None:
    tile_text = TESLA_TILE_PATH.read_text(encoding="utf-8")

    assert 'entity: binary_sensor.tesla_daily_plan_active\n            name: "Use Daily Plan"' in tile_text
    assert "state_color: true" in tile_text
    assert "service: input_boolean.turn_off" in tile_text
    assert "entity: input_boolean.long_range_travel\n            name: \"Use Daily Plan\"" not in tile_text


def test_storage_dashboard_uses_inverse_sensor_for_daily_plan_tile() -> None:
    dashboard_text = DASHBOARD_PATH.read_text(encoding="utf-8")

    assert '"entity": "binary_sensor.tesla_daily_plan_active"' in dashboard_text
    assert '"name": "Use Daily Plan"' in dashboard_text
    assert '"service": "input_boolean.turn_off"' in dashboard_text
    assert (
        '"entity": "input_boolean.long_range_travel",\n'
        '                  "tap_action": {\n'
        '                    "action": "call-service",\n'
        '                    "service": "input_boolean.turn_off"'
    ) not in dashboard_text

def test_home_default_charge_plan_skips_extra_tesla_schedule_override() -> None:
    package_text = CAR_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "{% set manage_tesla_schedule = (not preserve_default_charging_schedule) or charge_limit != 80 %}" in package_text
    assert "tesla_plan.manage_tesla_schedule" in package_text
    assert "No extra home charging override is needed." in package_text


def test_alarm_only_planner_skips_preconditioning_without_real_departure() -> None:
    package_text = CAR_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "{% set precondition = has_calendar_departure and departure_window_open and manage_tesla_schedule %}" in package_text
    assert (
        "{% set precondition = (has_calendar_departure or alarm_enabled) and departure_window_open %}"
        not in package_text
    )
    assert "skip cabin preconditioning until a real next-day departure is scheduled" in package_text


def test_dashboard_copy_explains_alarm_only_days_and_home_schedule_override_logic() -> None:
    tile_text = TESLA_TILE_PATH.read_text(encoding="utf-8")
    dashboard_text = DASHBOARD_PATH.read_text(encoding="utf-8")

    for text in (
        "Charge limit and any needed Tesla schedule override follow tomorrow's trip, alarm, weather, and EV tariff inputs",
        "Cabin preconditioning only runs when a real next-day departure is scheduled",
        "Planner is following tomorrow's alarm for charge-limit planning only",
        "Home Assistant may temporarily override Tesla scheduling at {{ location_label }} because extra home charging is needed",
        "Planner is keeping the Tesla app home schedule because no extra home charging is needed",
        "Preserve Tesla app default at {{ location_label }} because no extra home charging is needed",
    ):
        assert text in tile_text
        assert text in dashboard_text
