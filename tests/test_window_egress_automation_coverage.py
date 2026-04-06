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


def _template_sensor_block(path: Path, sensor_name: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"      - name: {sensor_name}"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find template sensor block {sensor_name!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("      - name: ") or lines[index].startswith("  - lock:"):
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
    block = _template_sensor_block(ZIGBEE_ZWAVE_PATH, "open_egress_points")

    assert "default_entity_id: sensor.open_egress_points" in block
    assert "entity_id.endswith('_contact')" not in block
    assert "device_class in ['door', 'window', 'opening']" in block
    for entity_id in (
        "binary_sensor.mailbox_contact",
        "binary_sensor.den_doors_contact",
        "binary_sensor.laundry_room_washing_machine_door_contact",
        "binary_sensor.nigori_windows",
        "binary_sensor.nigori_doors",
        "binary_sensor.nigori_trunk",
        "binary_sensor.nigori_frunk",
    ):
        assert entity_id in block
    assert "group.egress_points" not in block


def test_fresh_air_open_reuses_any_window_open_state() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    assert 'default_entity_id: binary_sensor.fresh_air_open' in text
    assert 'state: "{{ is_state(\'binary_sensor.any_window_open\', \'on\') }}"' in text
