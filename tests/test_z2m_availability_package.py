from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "z2m_availability.yaml"
Z2M_CONFIG_PATH = ROOT / "zigbee2mqtt" / "configuration.yaml"
GRAFANA_DASHBOARD_PATH = ROOT / "docs" / "grafana" / "z2m_availability_dashboard.json"


def _named_devices() -> list[str]:
    """Return all non-IEEE-address friendly names from the devices: section of Z2M config.

    Excludes groups (which appear after groups: key) and unnamed devices (IEEE addresses).
    """
    text = Z2M_CONFIG_PATH.read_text(encoding="utf-8")
    # Only look in the devices: block, not groups:
    devices_start = text.find("devices:")
    groups_start = text.find("groups:")
    if devices_start == -1:
        return []
    if groups_start != -1 and groups_start > devices_start:
        devices_text = text[devices_start:groups_start]
    else:
        devices_text = text[devices_start:]
    pattern = re.compile(r"^\s+friendly_name:\s+(.+)$", re.MULTILINE)
    names = []
    for match in pattern.finditer(devices_text):
        name = match.group(1).strip().strip("'\"")
        if not name.startswith("0x"):
            names.append(name)
    return names


def test_package_file_exists() -> None:
    assert PACKAGE_PATH.exists(), f"Package file not found: {PACKAGE_PATH}"


def test_package_has_mqtt_binary_sensor_section() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert "mqtt:" in text
    assert "binary_sensor:" in text


def test_bridge_sensor_present() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert "unique_id: z2m_bridge_availability" in text
    assert 'state_topic: "zigbee2mqtt/bridge/state"' in text
    assert "device_class: connectivity" in text


def test_all_named_devices_have_sensors() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    named_devices = _named_devices()
    missing = []
    for fn in named_devices:
        expected_topic = f'state_topic: "zigbee2mqtt/{fn}/availability"'
        if expected_topic not in text:
            missing.append(fn)
    assert not missing, f"Missing availability sensors for devices (first 10): {missing[:10]}"


def test_device_sensors_have_availability_gate() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert 'availability_topic: "zigbee2mqtt/bridge/state"' in text
    assert 'availability_template: "{{ value_json.state }}"' in text
    assert 'payload_available: "online"' in text
    assert 'payload_not_available: "offline"' in text


def test_device_sensors_use_json_state_template() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert 'value_template: "{{ value_json.state }}"' in text
    assert 'payload_on: "online"' in text
    assert 'payload_off: "offline"' in text


def test_unique_ids_are_unique() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    unique_ids = re.findall(r"unique_id:\s+(\S+)", text)
    assert len(unique_ids) == len(set(unique_ids)), (
        f"Duplicate unique_ids found: {[uid for uid in set(unique_ids) if unique_ids.count(uid) > 1]}"
    )


def test_aggregate_template_sensor_present() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert "template:" in text
    assert "unique_id: z2m_devices_offline" in text
    assert "device_class: problem" in text


def test_aggregate_template_has_attributes() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert "offline_devices:" in text
    assert "total_devices:" in text
    assert "online_count:" in text


def test_aggregate_template_searches_z2m_entities() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    assert "selectattr('entity_id', 'search', 'z2m_')" in text
    assert "selectattr('attributes.device_class', 'eq', 'connectivity')" in text
    assert "selectattr('state', 'eq', 'off')" in text


def test_package_does_not_duplicate_z2m_lifecycle_sensors() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    # These unique_ids belong to z2m_lifecycle.yaml — must not be redefined here
    assert "z2m_lifecycle_issues" not in text
    assert "z2m_failing_count" not in text
    assert "z2m_router_offline_pct" not in text
    assert "reboot_counter" not in text


def test_sensor_count_matches_device_count() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    named_devices = _named_devices()
    # Each device should have exactly one state_topic entry
    topic_pattern = re.compile(r'state_topic: "zigbee2mqtt/.+/availability"')
    sensor_topics = topic_pattern.findall(text)
    # +1 for bridge sensor which has a different topic pattern
    # bridge uses "zigbee2mqtt/bridge/state" not "/availability"
    assert len(sensor_topics) == len(named_devices), (
        f"Expected {len(named_devices)} device sensors, found {len(sensor_topics)}"
    )


def test_grafana_dashboard_is_valid_json() -> None:
    assert GRAFANA_DASHBOARD_PATH.exists(), f"Grafana dashboard not found: {GRAFANA_DASHBOARD_PATH}"
    content = GRAFANA_DASHBOARD_PATH.read_text(encoding="utf-8")
    dashboard = json.loads(content)
    assert isinstance(dashboard, dict)


def test_grafana_dashboard_has_required_panels() -> None:
    content = GRAFANA_DASHBOARD_PATH.read_text(encoding="utf-8")
    dashboard = json.loads(content)
    panels = [p for p in dashboard.get("panels", []) if p.get("type") != "row"]
    panel_types = {p["type"] for p in panels}
    assert "timeseries" in panel_types, "Missing timeseries panel"
    assert "stat" in panel_types, "Missing stat panel"
    assert "table" in panel_types, "Missing table panel"


def test_grafana_dashboard_targets_z2m_availability_entities() -> None:
    content = GRAFANA_DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "z2m_.*_availability" in content
    assert "binary_sensor.state" in content


def test_grafana_dashboard_has_influxdb_datasource() -> None:
    content = GRAFANA_DASHBOARD_PATH.read_text(encoding="utf-8")
    dashboard = json.loads(content)
    inputs = dashboard.get("__inputs", [])
    influxdb_inputs = [i for i in inputs if i.get("pluginId") == "influxdb"]
    assert len(influxdb_inputs) >= 1, "Dashboard missing InfluxDB datasource input"


def test_grafana_dashboard_uid_set() -> None:
    content = GRAFANA_DASHBOARD_PATH.read_text(encoding="utf-8")
    dashboard = json.loads(content)
    assert dashboard.get("uid"), "Dashboard missing uid field"
    assert dashboard.get("title"), "Dashboard missing title field"
