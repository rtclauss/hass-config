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
