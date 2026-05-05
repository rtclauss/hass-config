from __future__ import annotations

from pathlib import Path


WEATHER_PATH = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"


def test_car_window_alert_closes_windows_even_when_notification_is_throttled() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "alert_car_windows_open_pressure_dropping" in text
    assert "choose:" in text
    assert "action: cover.close_cover" in text
    assert "resource_template: >-" in text
    assert "timeout: 20" in text
    assert "state_attr('zone.home', 'latitude')" in text
    assert "state_attr('zone.home', 'longitude')" in text
    assert "latitude=0&longitude=0" not in text
    assert "Check if we already notified within the last hour" in text
    assert "action: notify.mobile_app_wethop" in text


def test_open_meteo_precipitation_template_handles_non_json_response() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "name: nigori_precip_next_2hr" in text
    assert "{% set payload = value_json if value_json is mapping else {} %}" in text
    assert "{% set hourly = payload.get('hourly', {}) %}" in text
    assert "value_json.hourly" not in text


def test_notify_weather_alert_uses_current_nws_alert_payload_shape() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "id: notify_weather_alert" in text
    assert "state_attr('sensor.nws_alerts', 'Alerts')" in text
    assert "primary_alert.Event" in text
    assert "primary_alert.Description" in text
    assert "primary_alert.Headline" in text
    assert "action: notify.notify_all" in text
    assert "message: >-\n            {{ state_attr('sensor.nws_alerts', 'Description') }}" not in text
