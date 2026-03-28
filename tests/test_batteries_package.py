from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATTERIES_PATH = ROOT / "packages" / "batteries.yaml"
CONFIG_PATH = ROOT / "configuration.yaml"


def _sensor_block(sensor_name: str) -> str:
    text = BATTERIES_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^      - name: {re.escape(sensor_name)}\n(.*?)(?=^      - name: |^automation:)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find template sensor block {sensor_name!r}")
    return match.group(0)


def _automation_block(automation_id: str) -> str:
    text = BATTERIES_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_battery_template_sensors_scan_all_battery_device_class_entities() -> None:
    block_20 = _sensor_block("battery_low_20")
    block_10 = _sensor_block("battery_low_10")

    assert "battery_exclude_entities: []" in block_20
    assert "variables: *battery_monitor_exclusions" in block_10

    for block, threshold in ((block_20, "20"), (block_10, "10")):
        assert f"default_entity_id: sensor.battery_low_{threshold}" in block
        assert "selectattr('attributes.device_class', 'eq', 'battery')" in block
        assert "rejectattr('entity_id', 'in', battery_exclude_entities)" in block
        assert f"if value < {threshold}" in block
        assert "tracked_count:" in block
        assert "summary: >-" in block
        assert "battery.state ~ '%'" in block


def test_battery_automations_update_notifications_from_dynamic_sensor_summaries() -> None:
    for automation_id, threshold in (
        ("notify_battery_dying_20", "20"),
        ("notify_battery_dying_10", "10"),
    ):
        block = _automation_block(automation_id)

        assert "mode: queued" in block
        assert "id: summary_change" in block
        assert "attribute: summary" in block
        assert "trigger: homeassistant" in block
        assert "id: startup_sync" in block
        assert "event: start" in block
        assert "persistent_notification.create" in block
        assert "persistent_notification.dismiss" in block
        assert "notify.all" in block
        assert f"states('sensor.battery_low_{threshold}')" in block
        assert f"state_attr('sensor.battery_low_{threshold}', 'summary')" in block
        assert "trigger.id == 'summary_change'" in block
        assert "count_increased" in block
        assert f"notification_id: low-battery-{threshold}" in block
        assert f"Battery Sensors Below {threshold}%" in block
        assert "trigger.from_state is not none" in block


def test_logbook_excludes_current_battery_monitor_entities_instead_of_stale_ones() -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")

    for entity_id in (
        "automation.notify_battery_dying_20",
        "automation.notify_battery_dying_10",
        "sensor.battery_low_20",
        "sensor.battery_low_10",
    ):
        assert entity_id in text

    for stale_entity_id in (
        "automation.battery_sensor_from_attributes",
        "automation.update_battery_status_group_members",
        "automation.battery_persistent_notification",
        "automation.battery_persistent_notification_clear",
    ):
        assert stale_entity_id not in text
