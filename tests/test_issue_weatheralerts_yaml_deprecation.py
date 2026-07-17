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
            "endsExpires": "null",
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
    assert "source_alerts = state_attr('sensor.nws_alerts', 'alerts')" in text
    assert "default(state_attr('sensor.nws_alerts', 'Alerts'), true)" in text
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
    assert "state_attr('sensor.nws_alerts', 'alerts')" in text
    assert "for alert in source_alerts if alert is mapping" in text
    assert "ns.alerts = ns.alerts + [dict(" in text
    assert "alert.get('ID', alert.get('Id', alert.get('id'" in text
    assert "alert.get('Event', alert.get('event'" in text
    assert "alert.get('Headline', alert.get('headline'" in text
    assert "alert.get('Description', alert.get('description'" in text
    assert "raw_ends_expires = alert.get('EndsExpires', alert.get('endsExpires', none))" in text
    assert "raw_ends_expires not in [none, '', 'null', 'None', 'NULL']" in text
    assert "else (ends if ends is not none else expires)" in text


def test_legacy_nws_alert_slots_guard_empty_source_lists_before_indexing() -> None:
    text = WEATHER_PATH.read_text(encoding="utf-8")

    assert "state_attr('sensor.nws_dakota_county_alerts', 'alerts')[0]" not in text
    assert "state_attr('sensor.nws_dakota_county_alerts', 'alerts')[1]" not in text
    assert "state_attr('sensor.nws_dakota_county_alerts', 'alerts')[2]" not in text
    assert "state_attr('sensor.nws_dakota_county_alerts', 'alerts')[3]" not in text
    assert "state_attr('sensor.nws_dakota_county_alerts', 'alerts')[4]" not in text

    for slot, minimum_count in enumerate(range(1, 6), start=1):
        assert (
            f"set alert = alerts[{slot - 1}] if alerts is sequence and "
            f"(alerts | count) > {slot - 1} else none"
        ) in text
        assert (
            "is_state('sensor.nws_dakota_county_alerts_alert_"
            f"{slot}', 'on') or (is_number(states('sensor.nws_dakota_county_alerts'))"
        ) not in text
        assert (
            "state_attr('sensor.nws_dakota_county_alerts', 'alerts') "
            f"| default([], true) | count) > {minimum_count - 1}"
        ) in text
