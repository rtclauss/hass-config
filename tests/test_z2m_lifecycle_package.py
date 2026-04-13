from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "z2m_lifecycle.yaml"
Z2M_CONFIG_PATH = ROOT / "zigbee2mqtt" / "configuration.yaml"


def _automation_block(automation_id: str) -> str:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_z2m_lifecycle_package_tracks_join_drop_leave_and_mesh_health() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    for token in (
        "topic: zigbee2mqtt/bridge/event",
        "topic: zigbee2mqtt/bridge/health",
        "topic: zigbee2mqtt/bridge/response/coordinator_check",
        "topic: zigbee2mqtt/+/availability",
        "'present_in_roster': false",
        "'last_interview_status': event_data.status",
        "joined and immediately left the network",
        "joined or announced but never stabilized",
        "left the network",
        "device interview failed",
        "coordinator_missing_routers",
    ):
        assert token in text


def test_z2m_lifecycle_package_exposes_decommission_controls_and_inventory_guidance() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "input_select:\n  z2m_decommission_device:" in text
    assert "z2m_decommission_selected_device:" in text
    assert "z2m_force_decommission_selected_device:" in text
    assert 'topic: zigbee2mqtt/bridge/request/device/remove' in text
    assert '{"id":"{{ device_id }}","force":false,"block":false}' in text
    assert '{"id":"{{ device_id }}","force":true,"block":false}' in text
    assert "inventory.md" in text
    assert "Update inventory.md in the repo" in text


def test_z2m_lifecycle_watchdog_uses_plain_bridge_state_trigger() -> None:
    block = _automation_block("shutdown_proxmox_z2m_unavailable")

    assert 'topic: zigbee2mqtt/bridge/state' in block
    assert 'payload: "offline"' in block
    assert 'value_template: "{{ value_json.state }}"' not in block


def test_zigbee2mqtt_configuration_enables_health_feed_and_does_not_disable_removal() -> None:
    text = Z2M_CONFIG_PATH.read_text(encoding="utf-8")

    assert "health:\n  interval: 10\n  reset_on_check: false" in text
    assert "disable_device_removal" not in text
