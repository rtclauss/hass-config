from __future__ import annotations

import os

from pathlib import Path
from privacy_ids import HOME_POSTAL_CODE, HOME_CITY_SLUG, HOME_CITY_TITLE, VEHICLE_ENTITY_SLUG, VEHICLE_TRACKER


ROOT = Path(__file__).resolve().parents[1]
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"
TESLA_TILE_PATH = ROOT / "lovelace" / "tiles" / "tiles_tesla_charging.yaml"
DASHBOARD_PATH = Path(os.environ.get("HA_DASHBOARD_PATH", ROOT / "tests" / "fixtures" / "dashboard.example.json"))


def test_utilities_package_defines_weekly_gas_price_and_ev_comparison_sensors() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    for token in (
        f"weekly_regular_gas_price_{HOME_POSTAL_CODE}_fallback:",
        "initial: 3.76",
        # EIA API replaces the defunct way.com scrape (issue #385)
        "resource: !secret eia_gas_price_mn_url",
        "api.eia.gov/v2/petroleum/pri/gnd/data/",
        "EMM_EPMRU_PTE_SMN_DPG",
        f"{HOME_CITY_SLUG}_weekly_regular_gas_price_live",
        "value_json.get('response'",
        f"weekly_regular_gas_price_{HOME_POSTAL_CODE}",
        "average_daily_ev_charging_cost",
        "average_daily_vehicle_miles",
        "average_daily_gas_car_cost_30mpg",
        "average_daily_ev_savings_vs_30mpg",
        "weekly_ev_charging:",
        "weekly_vehicle_mileage:",
        f"source: sensor.{VEHICLE_ENTITY_SLUG}_odometer",
    ):
        assert token in text


def test_tesla_yaml_tile_exposes_ev_vs_gas_comparison_entities() -> None:
    text = TESLA_TILE_PATH.read_text(encoding="utf-8")

    for token in (
        "sensor.average_daily_ev_charging_cost",
        "sensor.average_daily_vehicle_miles",
        "sensor.weekly_regular_gas_price_",
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
        '"entity": "sensor.weekly_regular_gas_price_',
        '"entity": "sensor.average_daily_gas_car_cost_30mpg"',
        '"entity": "sensor.average_daily_ev_savings_vs_30mpg"',
    ):
        assert token in text


def test_utilities_package_keeps_the_raw_meter_as_measurement_only() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    assert "name: house_electrical_meter" in text
    assert "state_class: total_increasing" in text
    assert "name: house_electrical_meter_non_ev" in text
    assert "state_class: total_increasing" in text
    assert f"states('{VEHICLE_TRACKER}') | default('', true) | lower != 'home'" in text
    assert f"home_charging = (states('{VEHICLE_TRACKER}') | default('', true) | lower) == 'home'" in text
