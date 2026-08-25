from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "z2m_lifecycle.yaml"
AVAILABILITY_PACKAGE_PATH = ROOT / "packages" / "z2m_availability.yaml"
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
        "topic: zigbee2mqtt/#",
        "'present_in_roster': false",
        "'last_interview_status': event_data.status",
        "joined and immediately left the network",
        "joined or announced but never stabilized",
        "left the network",
        "device interview failed",
        "coordinator_missing_routers",
    ):
        assert token in text


def test_z2m_lifecycle_notification_uses_latest_state_and_bounded_attributes() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    block = _automation_block("notify_z2m_lifecycle_issues")

    assert "mode: restart" in block
    assert "mode: queued" not in block
    assert "max: 10" not in block
    assert "devices: \"{{ z2m_lifecycle_stats.get('devices', {}) }}\"" not in text


def test_z2m_lifecycle_package_debounces_transient_coordinator_router_alerts() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "coordinator_issue_hold_seconds = 120" in text
    assert "current_attrs.get('coordinator_missing_routers_pending', coordinator_missing_routers)" in text
    assert (
        "current_attrs.get('coordinator_missing_routers_pending_since', (now_ts - coordinator_issue_hold_seconds) if coordinator_missing_routers | count > 0 else none)"
        in text
    )
    assert (
        "(now_ts - (coordinator_missing_routers_pending_since | default(0, true) | float(0))) >= coordinator_issue_hold_seconds"
        in text
    )


def test_z2m_lifecycle_package_exposes_decommission_controls_and_inventory_guidance() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "input_select:\n  z2m_decommission_device:" in text
    assert "z2m_decommission_selected_device:" in text
    assert "z2m_force_decommission_selected_device:" in text
    assert "z2m_decommission_device:" in text
    assert 'topic: zigbee2mqtt/bridge/request/device/remove' in text
    assert "force_remove: false" in text
    assert "force_remove: true" in text
    assert '{"id":"{{ device_id }}","force":{{ \'true\' if force_remove_bool else \'false\' }},"block":false}' in text
    assert "inventory.md" in text
    assert "Update inventory.md in the repo" in text


def test_z2m_lifecycle_watchdog_uses_plain_bridge_state_trigger() -> None:
    block = _automation_block("shutdown_proxmox_z2m_unavailable")

    assert 'topic: zigbee2mqtt/bridge/state' in block
    assert 'payload: "offline"' in block
    assert 'value_template: "{{ value_json.state }}"' not in block


def test_z2m_lifecycle_watchdog_treats_sustained_bridge_offline_as_issue() -> None:
    block = _automation_block("shutdown_proxmox_z2m_unavailable")

    # A debounced bridge-offline signal so a sustained bridge outage still
    # triggers recovery even when the add-on process is "running" and routers
    # have not dropped.
    assert "entity_id: binary_sensor.z2m_bridge" in block
    assert "id: bridge_offline_sustained" in block
    assert "bridge_offline_sustained: >-" in block
    assert "is_state('binary_sensor.z2m_bridge', 'off')" in block
    assert ">= 300" in block
    # issue_active and the escalation predicate must include the bridge signal.
    assert "or bridge_offline_sustained" in block
    assert "or is_state('binary_sensor.z2m_bridge', 'off')" in block
    # Recovery is only declared once the bridge is back.
    assert "and not is_state('binary_sensor.z2m_bridge', 'off')" in block


def test_z2m_lifecycle_watchdog_does_not_restart_for_ha_republish_candidates() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    watchdog = _automation_block("shutdown_proxmox_z2m_unavailable")
    reset = _automation_block("reset_z2m_reboot_counter")
    recovery_sensor = text.split("unique_id: z2m_recovery_candidates", maxsplit=1)[1]

    assert "sensor.z2m_recovery_candidates" not in watchdog
    assert "recovery_candidates_high" not in watchdog
    assert "Z2M recovery candidates exceeded threshold" not in watchdog
    assert "sensor.z2m_recovery_candidates" not in reset
    assert "Diagnostic only. Zigbee2MQTT 2.12.1 republishes bridge/state" in recovery_sensor


def test_z2m_reboot_counter_reset_combines_manual_and_recovery_paths() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    reset = _automation_block("reset_z2m_reboot_counter")

    assert "reset_z2m_reboot_counter_on_recovery" not in text
    assert "event_type: mobile_app_notification_action" in reset
    assert "action: REBOOT_Z2M_COUNTER" in reset
    assert "id: manual_reset" in reset
    assert reset.count("id: sustained_recovery") == 3
    assert "entity_id: binary_sensor.zigbee2mqtt_running" in reset
    assert "entity_id: binary_sensor.z2m_failing" in reset
    assert reset.count("minutes: 10") == 2
    assert "condition: numeric_state" in reset
    assert "entity_id: counter.reboot_counter" in reset
    assert reset.count("action: script.z2m_reset_reboot_counter") == 1


def test_z2m_router_stats_preserves_roster_on_malformed_or_empty_devices_response() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    availability_text = AVAILABILITY_PACKAGE_PATH.read_text(encoding="utf-8")
    triggers = text.split("z2m_router_stats: >-", maxsplit=1)[0].rsplit("\n  - trigger:\n", maxsplit=1)[1]
    block = text.split("z2m_router_stats: >-", maxsplit=1)[1].split("  - binary_sensor:", maxsplit=1)[0]
    availability_depths = {
        name.count("/") + 1
        for name in re.findall(r'state_topic: "zigbee2mqtt/(.+)/availability"', availability_text)
    }

    assert "current_attrs.get('routers', [])" in block
    assert "topic: zigbee2mqtt/#" not in triggers
    for depth in availability_depths:
        assert f"topic: zigbee2mqtt/{'/'.join('+' for _ in range(depth))}/availability" in triggers
    assert "payload.data is not mapping" in block
    assert "payload is not mapping" in block
    assert "{% set has_device_snapshot = devices | count > 0 %}" in block
    assert "{% if has_device_snapshot %}" in block
    assert "{% set routers = devices" in block


def test_z2m_ota_template_tracks_progress_attributes_not_simple_availability() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    template_block = text.split("z2m_ota_stats: >-", maxsplit=1)[1].split("  - trigger:", maxsplit=1)[0]

    assert "entity_id.startswith('update.')" in template_block
    assert "state_attr(entity_id, 'in_progress')" in template_block
    assert "state_attr(entity_id, 'update_percentage')" in template_block
    assert "'eta_minutes': eta_minutes" in template_block
    assert "is_state(entity_id, 'on')" not in template_block
    assert "states(entity_id) == 'on'" not in template_block
    assert "states(entity_id) in ['on'" not in template_block


def test_z2m_recovery_candidates_uses_active_roster_not_global_state_scan() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    sensor_block = text.split("unique_id: z2m_recovery_candidates", maxsplit=1)[1]

    assert "state_attr('sensor.z2m_lifecycle_issues', 'selection_map')" in sensor_block
    assert "integration_entities('mqtt')" in sensor_block
    assert "active_ids.values" in sensor_block
    assert "device_attr(ha_device_id, 'identifiers')" in sensor_block
    assert "active_id in identifiers_text" in sensor_block
    assert "is_state(eid, 'unavailable')" in sensor_block
    assert "for s in states" not in sensor_block


def test_zigbee2mqtt_configuration_enables_health_feed_and_does_not_disable_removal() -> None:
    text = Z2M_CONFIG_PATH.read_text(encoding="utf-8")

    assert "health:\n  interval: 10\n  reset_on_check: false" in text
    assert "disable_device_removal" not in text
