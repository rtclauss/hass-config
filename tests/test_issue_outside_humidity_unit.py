from __future__ import annotations

from pathlib import Path


WEATHER_PATH = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"


def test_outside_humidity_sensor_uses_percent_unit() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    block = text.split("- name: outside_humidity", 1)[1].split("- name: outside_temperature", 1)[0]
    assert 'device_class: humidity' in block
    assert 'unit_of_measurement: "%"' in block
