from __future__ import annotations

from pathlib import Path

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import pytest
import yaml


ALERTS_PATH = Path(__file__).resolve().parents[1] / "packages" / "alerts.yaml"


@pytest.mark.parametrize("service", ["all", "notify_all"])
@pytest.mark.parametrize(
    ("payload", "tv_state", "expected"),
    [
        ({"message": "Kitchen leak detected"}, "on", True),
        ({"message": "Mail arrived", "title": "Mail", "data": {"tag": "mail"}}, "on", True),
        ({"message": "Kitchen leak detected"}, "off", False),
        ({"message": "Kitchen leak detected"}, "unavailable", False),
        ({"message": "Kitchen leak detected"}, "unknown", False),
        ({"message": "clear_notification", "data": {"tag": "mail"}}, "on", False),
        ({"message": " CLEAR_NOTIFICATION \n"}, "on", False),
        ({"message": "Hall sensor battery is low"}, "on", False),
        ({"message": "Replace the batteries"}, "on", False),
        ({"message": "Hall sensor: 5%", "title": "LOW BATTERY"}, "on", False),
        ({"message": "Hall sensor: 5%", "title": "Low Batteries"}, "on", False),
        ({"message": "Hall sensor: 5%", "data": {"tag": "battery_alert"}}, "on", False),
        ({"message": "Hall sensor: 5%", "data": {"channel": "Batteries"}}, "on", False),
        ({"message": "Hall sensor: 5%", "data": {"group": "Battery alerts"}}, "on", False),
        ({"message": "Mail arrived", "title": None, "data": None}, "on", True),
        ({"message": "Mail arrived", "data": {"tag": None}}, "on", True),
        ({"message": ""}, "on", False),
        ({"message": " \n"}, "on", False),
        ({"message": None}, "on", False),
        ({}, "on", False),
    ],
)
def test_lg_tv_notification_routing(payload: dict, tv_state: str, expected: bool, service: str) -> None:
    """Render the configured guards against shared-notification payloads."""
    text = ALERTS_PATH.read_text(encoding="utf-8")
    block = "  - alias: mirror_shared_notifications_to_lg_tv_when_on"
    mirror_yaml = block + text.split(block, maxsplit=1)[1].split("\n  - alias:", maxsplit=1)[0]
    mirror = yaml.safe_load(mirror_yaml)[0]
    event_data = {"domain": "notify", "service": service, "service_data": payload}
    assert any(
        all(event_data[key] == value for key, value in trigger["event_data"].items())
        for trigger in mirror["trigger"]
    )
    env = NativeEnvironment(undefined=StrictUndefined)
    context = {"trigger": {"event": {"data": event_data}}}
    for name, template in mirror["variables"].items():
        context[name] = env.from_string(template).render(**context)

    results = []
    for condition in mirror["condition"]:
        if condition["condition"] == "state":
            assert condition["entity_id"] == "media_player.lg_webos_smart_tv"
            results.append(tv_state == condition["state"])
        else:
            assert condition["condition"] == "template"
            results.append(bool(env.from_string(condition["value_template"]).render(**context)))
    assert all(results) is expected
    if expected:
        data = mirror["action"][0]["data"]
        assert env.from_string(data["message"]).render(**context) == payload["message"]
        assert env.from_string(data["data"]).render(**context) == (payload.get("data") or {})


def test_notify_groups_do_not_include_lg_webos_service() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")

    assert "- name: all" in text
    assert "- name: notify_all" in text
    assert "mobile_app_personal_macbook" in text
    notify_section = text.split("########################\n# Notify", maxsplit=1)[1]
    notify_section = notify_section.split("########################\n# Scenes", maxsplit=1)[0]
    assert "lg_webos_tv_oled65c4aua_dusqljr" not in notify_section


def test_shared_notifications_mirror_to_lg_tv_only_when_on() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")

    assert "id: mirror_shared_notifications_to_lg_tv_when_on" in text
    assert "event_type: call_service" in text
    assert "domain: notify" in text
    assert "service: all" in text
    assert "service: notify_all" in text
    assert "trigger.event.data.service_data" in text
    assert "entity_id: media_player.lg_webos_smart_tv" in text
    assert 'state: "on"' in text
    assert "action: notify.lg_webos_tv_oled65c4aua_dusqljr" in text


def test_shared_notifications_mirror_defaults_optional_payload_fields() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    mirror = text.split("id: mirror_shared_notifications_to_lg_tv_when_on", maxsplit=1)[1]

    assert "notify_title: \"{{ notify_payload.title | default('', true) }}\"" in mirror
    assert "notify_data: \"{{ notify_payload.data | default({}, true) }}\"" in mirror


def test_water_leak_triggers_follow_replacement_sensors_in_monitored_areas() -> None:
    # Native moisture triggers reject unknown/unavailable transitions and retain
    # wet/dry IDs for the existing notification branches.
    text = ALERTS_PATH.read_text(encoding="utf-8")
    block = text.split("  - id: water_leak_detected\n", 1)[1].split("\n  - id:", 1)[0]
    config = yaml.safe_load(block)
    wet, dry = config["trigger"]
    assert wet["trigger"] == "moisture.detected"
    assert dry["trigger"] == "moisture.cleared"
    assert wet["id"] == "wet" and dry["id"] == "dry"
    assert wet["target"] == dry["target"] == {
        "area_id": ["unfinished_basement", "kitchen", "laundry_room"]
    }
    assert wet["options"] == dry["options"] == {"behavior": "each"}
    assert "binary_sensor.kitchen_sink_leak_water_leak" not in block
    assert "binary_sensor.laundry_room_leak_water_leak" not in block


def test_flash_lights_keeps_distinct_on_and_off_hold_steps() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    script = text.split("  flash_lights:", maxsplit=1)[1]

    assert "alias: Hold lights on\n        delay:\n          seconds: 1" in script
    assert "alias: Hold lights off\n        delay:\n          seconds: 1" in script
