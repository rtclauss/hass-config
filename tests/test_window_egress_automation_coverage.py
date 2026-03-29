from pathlib import Path


ALERTS_PATH = Path(__file__).resolve().parents[1] / "packages" / "alerts.yaml"
CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"
ZONE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zone.yaml"
ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    id_line = f"  - id: {automation_id}"
    start = None

    for index, line in enumerate(lines):
        if line != id_line:
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_motion_detected_on_trip_watches_all_known_window_and_egress_contacts() -> None:
    block = _automation_block(ALERTS_PATH, "motion_detected_on_trip")

    assert "entity_id: binary_sensor.any_egress_open" in block
    assert 'from: "off"' in block
    assert 'to: "on"' in block
    assert "entity_id: binary_sensor.office_occupancy_2" in block
    assert "state_attr('sensor.open_egress_points', 'friendly_names')" in block
    assert "| default('', true)" in block
    assert "trigger_label" in block
    assert "Activity detected at {{ trigger_label }} while you're away!" in block
    assert "group.egress_points" not in block


def test_doors_open_when_leaving_home_checks_windows_and_doors() -> None:
    block = _automation_block(ZONE_PATH, "doors_open_when_leaving_home")

    assert "entity_id: binary_sensor.any_egress_open" in block
    assert 'state: "on"' in block
    assert "state_attr('sensor.open_egress_points', 'friendly_names')" in block
    assert "| default('', true)" in block
    assert "Door or window left open: {{ open_egress_points }}." in block
    assert "group.egress_points" not in block


def test_dynamic_egress_sensors_replace_legacy_group() -> None:
    text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    assert "default_entity_id: sensor.open_egress_points" in text
    assert "default_entity_id: binary_sensor.any_egress_open" in text
    assert "entity_id.endswith('_contact')" in text
    assert "device_class in ['door', 'window', 'opening']" in text
    assert "binary_sensor.mailbox_contact" in text
    assert "group.egress_points" not in text


def test_fresh_air_open_reuses_any_window_open_state() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    assert 'default_entity_id: binary_sensor.fresh_air_open' in text
    assert 'state: "{{ is_state(\'binary_sensor.any_window_open\', \'on\') }}"' in text
