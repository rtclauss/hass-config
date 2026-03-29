from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AIRPLANES_PATH = ROOT / "packages" / "airplanes.yaml"
BIRDS_PATH = ROOT / "packages" / "birds.yaml"


def test_garden_birds_sensor_handles_missing_common_name_without_template_errors() -> None:
    text = BIRDS_PATH.read_text(encoding="utf-8")

    assert 'name: "Garden Birds"' in text
    assert "value_json is mapping" in text
    assert "value_json.common_name is defined" in text
    assert "unknown" in text


def test_airplanes_package_uses_single_routeset_fetch_and_derives_display_sensors_from_raw() -> None:
    text = AIRPLANES_PATH.read_text(encoding="utf-8")

    assert text.count("resource: https://adsb.im/api/0/routeset") == 1
    assert "name: Closest Aircraft Routeset Raw" in text
    assert "unique_id: closest_aircraft_routeset_raw" in text
    assert "state_attr('sensor.closest_aircraft_overhead','callsign')" in text
    assert "name: Closest Aircraft Routeset" in text
    assert "unique_id: closest_aircraft_routeset" in text
    assert "name: Closest Aircraft Routeset Names" in text
    assert "unique_id: closest_aircraft_routeset_names" in text
    assert "states('sensor.closest_aircraft_routeset_raw')" in text
    assert "sensor.closest_aircraft_routeset_raw" in text


def test_aircraft_refresh_automation_updates_the_raw_routeset_sensor() -> None:
    text = AIRPLANES_PATH.read_text(encoding="utf-8")

    assert "id: adsb_refresh_rest_on_hex_change" in text
    assert "- sensor.closest_aircraft_routeset_raw" in text
    assert "- sensor.closest_aircraft_route_raw" in text
    assert "- sensor.closest_aircraft_photo_raw" in text
    assert "- sensor.closest_aircraft_photo" in text
