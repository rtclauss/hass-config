from __future__ import annotations

from pathlib import Path

import jinja2
import yaml


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
    assert text.count(guard) == 3
    assert "{{ payload.get('photos', []) | length }}" in text
    assert "{{ 'response' in payload }}" in text
    assert "value_json.photos" not in text
    assert "value_json.response" not in text


def _adsb_raw_value_template() -> str:
    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
    data = yaml.load(AIRPLANES_PATH.read_text(encoding="utf-8"), Loader=_Loader)
    (sensor,) = [s for s in data["sensor"] if s.get("unique_id") == "adsb_aircraft_raw"]
    return sensor["value_template"]


def test_adsb_aircraft_raw_template_guards_non_json_responses() -> None:
    template = _adsb_raw_value_template()

    assert "value_json.now" not in template
    assert "value_json is defined and value_json is mapping" in template


def test_adsb_aircraft_raw_template_renders_safely() -> None:
    template = jinja2.Environment().from_string(_adsb_raw_value_template())

    # Receiver outage: HA leaves value_json undefined for non-JSON bodies.
    assert template.render().strip() == "unknown"
    # Valid JSON that is not a mapping, or a mapping without/with null "now".
    assert template.render(value_json=["not", "a", "dict"]).strip() == "unknown"
    assert template.render(value_json="error page").strip() == "unknown"
    assert template.render(value_json={"aircraft": []}).strip() == "unknown"
    assert template.render(value_json={"now": None}).strip() == "unknown"
    # Good payload keeps the existing timestamp state.
    payload = {"now": 1792000000.5, "aircraft": [{"hex": "abc123"}]}
    assert template.render(value_json=payload).strip() == "1792000000.5"
