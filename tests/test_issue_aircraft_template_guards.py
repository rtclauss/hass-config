from __future__ import annotations

from pathlib import Path


AIRPLANES_PATH = Path(__file__).resolve().parents[1] / "packages" / "airplanes.yaml"


def test_closest_aircraft_templates_guard_missing_attributes_and_home_zone() -> None:
    text = AIRPLANES_PATH.read_text(encoding="utf-8")

    assert "this.attributes.get('raw')" in text
    assert "this.attributes.get('distance_km')" in text
    assert "home_lat is not none and home_lon is not none" in text
    assert "{{ d_km | round(3) if d_km is not none else none }}" in text
    assert "{{ (distance_km | float(default=0)) * 0.621371 | round(2) }}" in text


def test_aircraft_rest_templates_handle_non_json_responses() -> None:
    text = AIRPLANES_PATH.read_text(encoding="utf-8")

    guard = "{% set payload = value_json if value_json is defined and value_json is mapping else {} %}"
    assert text.count(guard) == 2
    assert "{{ payload.get('photos', []) | length }}" in text
    assert "{{ 'response' in payload }}" in text
    assert "value_json.photos" not in text
    assert "value_json.response" not in text
