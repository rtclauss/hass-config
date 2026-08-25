from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "inovelli_led_notifications.yaml"


def _script_block(script_id: str) -> str:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  {re.escape(script_id)}:\n(.*?)(?=^  [A-Za-z0-9_]+:\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find script {script_id!r}")
    return match.group(0)


def test_inovelli_effect_scripts_no_longer_expand_multi_integration_blueprint() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "use_blueprint:" not in text
    for unsupported_action in (
        "zha.issue_zigbee_cluster_command",
        "zha.set_zigbee_cluster_attribute",
        "zwave_js.bulk_set_partial_config_parameters",
        "zwave_js.set_config_parameter",
    ):
        assert unsupported_action not in text


def test_inovelli_publisher_targets_only_active_z2m_devices() -> None:
    block = _script_block("publish_inovelli_z2m_led_effect")

    for token in (
        "selectattr('domain', 'in', ['light', 'fan'])",
        "selectattr('entity_id', 'is_device_attr', 'manufacturer', 'Inovelli')",
        "selectattr('entity_id', 'in', integration_entities('mqtt'))",
        "rejectattr('state', 'in', ['unknown', 'unavailable'])",
        "rejectattr('attributes.restored', 'eq', true)",
        "action: mqtt.publish",
        "zigbee2mqtt/{{ state_attr(repeat.item, 'friendly_name') }}/set",
        "payload: \"{{ effect_payload }}\"",
    ):
        assert token in block


def test_inovelli_aurora_wrapper_preserves_z2m_effect_payload() -> None:
    block = _script_block("inovelli_led_aurora_notification")

    for token in (
        "action: script.publish_inovelli_z2m_led_effect",
        "color: 190",
        "duration: 70",
        "effect: aurora",
        "level: 130",
    ):
        assert token in block


def test_inovelli_clear_wrapper_preserves_z2m_effect_payload() -> None:
    block = _script_block("inovelli_led_clear_all_effects")

    for token in (
        "action: script.publish_inovelli_z2m_led_effect",
        "color: 0",
        "duration: 0",
        "effect: clear_effect",
        "level: 281",
    ):
        assert token in block
