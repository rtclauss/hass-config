from __future__ import annotations

from pathlib import Path


WEATHER_PATH = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"


def test_weather_package_uses_ui_managed_nws_alerts_instead_of_weatheralerts_yaml() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "sensor.nws_alerts" in text
    assert "sensor.nws_dakota_county_alerts_active_alerts" in text
    assert "sensor.nws_dakota_county_alerts_alerts_are_active" in text
    assert "- platform: weatheralerts" not in text
    assert "state: !secret home_state" not in text
    assert "zone: !secret nws_zone" not in text
    assert "county: !secret nws_county" not in text
