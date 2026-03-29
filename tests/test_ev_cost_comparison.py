from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"
TESLA_TILE_PATH = ROOT / "lovelace" / "tiles" / "tiles_tesla_charging.yaml"
DASHBOARD_PATH = ROOT / ".storage" / "lovelace.ryan_new_mushroom"


def test_utilities_package_defines_weekly_gas_price_and_ev_comparison_sensors() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    for token in (
        "weekly_regular_gas_price_55125_fallback:",
        "initial: 3.76",
        "resource: https://www.way.com/gas/prices/minnesota/woodbury",
        "woodbury_weekly_regular_gas_price_live",
        "Week Ago Avg.",
        "weekly_regular_gas_price_55125",
        "average_daily_ev_charging_cost",
        "average_daily_vehicle_miles",
        "average_daily_gas_car_cost_30mpg",
        "average_daily_ev_savings_vs_30mpg",
        "weekly_ev_charging:",
        "weekly_vehicle_mileage:",
        "source: sensor.nigori_odometer",
    ):
        assert token in text


def test_tesla_yaml_tile_exposes_ev_vs_gas_comparison_entities() -> None:
    text = TESLA_TILE_PATH.read_text(encoding="utf-8")

    for token in (
        "sensor.average_daily_ev_charging_cost",
        "sensor.average_daily_vehicle_miles",
        "sensor.weekly_regular_gas_price_55125",
        "sensor.average_daily_gas_car_cost_30mpg",
        "sensor.average_daily_ev_savings_vs_30mpg",
        "Avg Gas Cost / Day @ 30 MPG",
        "EV Savings / Day vs 30 MPG",
    ):
        assert token in text


def test_storage_dashboard_exposes_ev_vs_gas_comparison_tiles() -> None:
    text = DASHBOARD_PATH.read_text(encoding="utf-8")

    for token in (
        '"entity": "sensor.average_daily_ev_charging_cost"',
        '"entity": "sensor.average_daily_vehicle_miles"',
        '"entity": "sensor.weekly_regular_gas_price_55125"',
        '"entity": "sensor.average_daily_gas_car_cost_30mpg"',
        '"entity": "sensor.average_daily_ev_savings_vs_30mpg"',
    ):
        assert token in text


def test_utilities_package_keeps_the_raw_meter_as_measurement_only() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    assert "name: house_electrical_meter" in text
    assert "state_class: measurement" in text
    assert "name: house_electrical_meter_non_ev" in text
    assert "state_class: total_increasing" in text
    assert "states('device_tracker.nigori_location_tracker') | default('', true) | lower != 'home'" in text
    assert "home_charging = (states('device_tracker.nigori_location_tracker') | default('', true) | lower) == 'home'" in text
