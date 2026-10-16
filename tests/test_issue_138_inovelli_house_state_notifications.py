from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "inovelli_house_state_notifications.yaml"

TARGETS = [
    "light.hall_transition_switch",
    "light.laundry_wall_switch",
    "light.garage_overhead_switch",
]


def _script_block(script_id: str) -> str:
    lines = PACKAGE_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {script_id}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break
    return "\n".join(lines[start:end])


def _automation_block(automation_id: str) -> str:
    lines = PACKAGE_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  - id: {automation_id}")
    return "\n".join(lines[start:])


def test_three_house_state_effects_share_the_verified_target_set() -> None:
    # (effect, Z2M hue, level = brightness * 10) mirror the retired blueprint mapping.
    expected = {
        "inovelli_house_state_front_door_unlocked": ("pulse", 0, 40),
        "inovelli_house_state_garage_open": ("pulse", 8, 30),
        "inovelli_house_state_mail_waiting": ("solid", 127, 20),
    }

    for script_id, (effect, color, level) in expected.items():
        block = _script_block(script_id)
        assert "action: script.publish_inovelli_z2m_led_effect" in block
        assert f"effect: {effect}" in block
        assert f"color: {color}" in block
        assert f"level: {level}" in block
        assert "duration: 255" in block
        assert "use_blueprint" not in block

    package_text = PACKAGE_PATH.read_text(encoding="utf-8")
    first_effect = _script_block("inovelli_house_state_front_door_unlocked")
    for entity_id in TARGETS:
        assert f"- {entity_id}" in first_effect
    assert package_text.count("entity_ids: *house_state_led_targets") == 3
    clear = _script_block("inovelli_house_state_clear")
    assert "effect: clear_effect" in clear
    assert "level: 281" in clear
    assert "zha." not in package_text and "zwave_js." not in package_text


def test_coordinator_uses_native_conditions_in_documented_priority_order() -> None:
    coordinator = _script_block("apply_inovelli_house_state_notification")
    ordered_tokens = [
        "entity_id: input_boolean.trip",
        "entity_id: lock.front_door_lock",
        "action: script.inovelli_house_state_front_door_unlocked",
        "entity_id: cover.garage_door",
        "action: script.inovelli_house_state_garage_open",
        "entity_id: input_boolean.mail_delivered",
        "action: script.inovelli_house_state_mail_waiting",
        "action: script.inovelli_house_state_clear",
    ]
    positions = [coordinator.index(token) for token in ordered_tokens]

    assert positions == sorted(positions)
    assert coordinator.count("condition: state") == 4
    for state in ("unlocked", "unlocking", "open", "opening", "jammed"):
        assert f"- {state}" in coordinator
    assert 'state: "off"' in coordinator
    assert 'state: "on"' in coordinator


def test_sync_automation_rechecks_sources_and_restarts_to_latest_state() -> None:
    automation = _automation_block("sync_inovelli_house_state_notification")

    for token in (
        "trigger: homeassistant",
        "event: start",
        "trigger: state",
        "- lock.front_door_lock",
        "- cover.garage_door",
        "- input_boolean.mail_delivered",
        "entity_id: input_boolean.trip",
        'to: "off"',
        "entity_id: script.reset_inovelli_switches",
        "id: reset_completed",
        "condition: trigger",
        '- delay: "00:10:00"',
        "action: script.apply_inovelli_house_state_notification",
        "mode: restart",
    ):
        assert token in automation


def test_package_has_no_direct_mqtt_device_commands() -> None:
    package_text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "mqtt.publish" not in package_text
    assert "zigbee2mqtt/" not in package_text
