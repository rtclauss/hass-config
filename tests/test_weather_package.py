from __future__ import annotations

from pathlib import Path


WEATHER_PATH = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"


def test_car_window_alert_closes_windows_even_when_notification_is_throttled() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "alert_car_windows_open_pressure_dropping" in text
    assert "choose:" in text
    assert "action: cover.close_cover" in text
    assert "resource_template: >-" in text
    assert "state_attr('zone.home', 'latitude')" in text
    assert "state_attr('zone.home', 'longitude')" in text
    assert "latitude=0&longitude=0" not in text
    assert "Check if we already notified within the last hour" in text
    assert "action: notify.mobile_app_wethop" in text
