from __future__ import annotations

from pathlib import Path


WEATHER_PATH = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"

NWS_ALERT_PAYLOAD_FIXTURES = (
    [],
    [
        {
            "ID": "one",
            "Event": "Severe Thunderstorm Warning",
            "Headline": "First headline",
            "Description": "First description",
            "Ends": "2026-06-18T22:00:00+00:00",
            "Expires": "2026-06-18T22:00:00+00:00",
        }
    ],
    [
        {
            "ID": "one",
            "Event": "Severe Thunderstorm Warning",
            "Headline": "First headline",
            "Description": "First description",
            "Ends": "2026-06-18T22:00:00+00:00",
        },
        {
            "id": "two",
            "event": "Flood Advisory",
            "headline": "Second headline",
            "description": "Second description",
            "expires": "2026-06-18T23:00:00+00:00",
        },
    ],
)


def test_weather_package_uses_ui_managed_nws_alerts_instead_of_weatheralerts_yaml() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "sensor.nws_alerts" in text
    assert "sensor.nws_dakota_county_alerts_active_alerts" in text
    assert "sensor.nws_dakota_county_alerts_alerts_are_active" in text
    assert "- platform: weatheralerts" not in text
    assert "state: !secret home_state" not in text
    assert "zone: !secret nws_zone" not in text
    assert "county: !secret nws_county" not in text


def test_weather_package_restores_legacy_nws_raw_source_from_ui_managed_payload() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "name: nws_dakota_county_alerts" in text
    assert "unique_id: nws_dakota_county_alerts_legacy_raw_source" in text
    assert "source_entity_id: sensor.nws_alerts" in text
    assert "source_alerts = state_attr('sensor.nws_alerts', 'Alerts')" in text
    assert "state: \"{{ states('sensor.nws_alerts') | int(0) }}\"" in text

    for legacy_field in (
        "id=",
        "event=",
        "area=",
        "NWSheadline=",
        "description=",
        "messageType=",
        "sent=",
        "effective=",
        "ends=",
        "expires=",
        "endsExpires=",
        "title=",
        "zoneid=",
    ):
        assert legacy_field in text

    assert len(NWS_ALERT_PAYLOAD_FIXTURES) == 3
    assert "state_attr('sensor.nws_alerts', 'Alerts') | default([], true)" in text
    assert "for alert in source_alerts if alert is mapping" in text
    assert "ns.alerts = ns.alerts + [dict(" in text
    assert "alert.get('ID', alert.get('Id', alert.get('id'" in text
    assert "alert.get('Event', alert.get('event'" in text
    assert "alert.get('Headline', alert.get('headline'" in text
    assert "alert.get('Description', alert.get('description'" in text
    assert "alert.get('EndsExpires', alert.get('endsExpires', ends if ends is not none else expires))" in text
