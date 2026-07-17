from __future__ import annotations

from pathlib import Path


ALERTS_PATH = Path(__file__).resolve().parents[1] / "packages" / "alerts.yaml"


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


def test_laundry_leak_dry_trigger_uses_on_to_off_transition() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    laundry_triggers = text.split(
        "entity_id: binary_sensor.laundry_room_leak_water_leak", maxsplit=1
    )[1]

    assert 'from: "off"\n        to: "on"\n        id: wet' in laundry_triggers
    assert 'from: "on"\n        to: "off"\n        id: dry' in laundry_triggers


def test_flash_lights_keeps_distinct_on_and_off_hold_steps() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    script = text.split("  flash_lights:", maxsplit=1)[1]

    assert "alias: Hold lights on\n        delay:\n          seconds: 1" in script
    assert "alias: Hold lights off\n        delay:\n          seconds: 1" in script
