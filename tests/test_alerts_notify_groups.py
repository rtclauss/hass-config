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
    assert "notify_payload.title | default('Home Assistant', true)" in text
    assert "notify_payload.data | default({}, true)" in text
    assert "entity_id: media_player.lg_webos_smart_tv" in text
    assert 'state: "on"' in text
    assert "action: notify.lg_webos_tv_oled65c4aua_dusqljr" in text


def test_laundry_leak_dry_trigger_detects_return_to_dry() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")

    assert (
        'entity_id: binary_sensor.laundry_room_leak_water_leak\n'
        '        from: "on"\n'
        '        to: "off"\n'
        "        id: dry"
    ) in text
