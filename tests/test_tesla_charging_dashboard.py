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
