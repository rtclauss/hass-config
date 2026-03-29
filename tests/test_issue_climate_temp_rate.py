from __future__ import annotations

from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"


def test_house_temp_rate_templates_guard_missing_change_rate_attributes() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    assert "state_attr('sensor.house_temperature_stats_1h', 'change_rate') is not none" in text
    assert "state_attr('sensor.house_temperature_stats_30m', 'change_rate') is not none" in text
    assert "{% set change_rate = state_attr('sensor.house_temperature_stats_1h', 'change_rate') %}" in text
    assert "{% set change_rate = state_attr('sensor.house_temperature_stats_30m', 'change_rate') %}" in text
    assert "{{ (change_rate | float(default=0)) * 60.0 * 5.0 }}" in text
