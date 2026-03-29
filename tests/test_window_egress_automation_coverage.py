from pathlib import Path


ALERTS_PATH = Path(__file__).resolve().parents[1] / "packages" / "alerts.yaml"
CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"
ZONE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zone.yaml"
ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"

EGRESS_ENTITY_IDS = (
    "binary_sensor.basement_window_contact",
    "binary_sensor.unfinished_basement_window_contact",
    "binary_sensor.se_basement_window_contact",
    "binary_sensor.sw_basement_window_contact",
    "binary_sensor.deck_door_contact",
    "binary_sensor.dining_room_north_window_contact",
    "binary_sensor.dining_room_south_window_contact",
    "binary_sensor.ene_window_contact",
    "binary_sensor.ese_window_contact",
    "binary_sensor.guest_bathroom_window_contact",
    "binary_sensor.guest_room_window_contact",
    "binary_sensor.hall_garage_entry_contact",
    "binary_sensor.kitchen_bay_middle_window_contact",
    "binary_sensor.kitchen_bay_north_window_contact",
    "binary_sensor.kitchen_bay_south_window_contact",
    "binary_sensor.kitchen_north_window_contact",
    "binary_sensor.kitchen_south_window_contact",
    "binary_sensor.main_foyer_front_door_contact",
    "binary_sensor.nne_window_contact",
    "binary_sensor.north_kitchen_sink_window_contact",
    "binary_sensor.north_master_bedroom_window_contact",
    "binary_sensor.nw_basement_window_contact",
    "binary_sensor.office_window_contact",
    "binary_sensor.office_north_window_contact",
    "binary_sensor.owner_suite_bathroom_bay_north_middle_window_contact",
    "binary_sensor.owner_suite_bathroom_bay_north_window_contact",
    "binary_sensor.owner_suite_bathroom_bay_south_middle_window_contact",
    "binary_sensor.owner_suite_bathroom_bay_south_window_contact",
    "binary_sensor.owner_suite_north_window_contact",
    "binary_sensor.owner_suite_south_window_contact",
    "binary_sensor.powder_room_window_contact",
    "binary_sensor.sse_window_contact",
    "binary_sensor.tiki_room_deck_contact",
)


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

    assert "entity_id: group.egress_points" in block
    assert "entity_id: binary_sensor.office_occupancy_2" in block
    assert "expand('group.egress_points')" in block
    assert "trigger_label" in block
    assert "Activity detected at {{ trigger_label }} while you're away!" in block


def test_doors_open_when_leaving_home_checks_windows_and_doors() -> None:
    block = _automation_block(ZONE_PATH, "doors_open_when_leaving_home")

    assert "entity_id: group.egress_points" in block
    assert 'state: "on"' in block
    assert "expand('group.egress_points')" in block
    assert "Door or window left open: {{ open_egress_points }}." in block


def test_egress_group_centralizes_all_window_and_door_contacts() -> None:
    text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    for entity_id in EGRESS_ENTITY_IDS:
        assert entity_id in text


def test_fresh_air_open_reuses_any_window_open_state() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    assert 'default_entity_id: binary_sensor.fresh_air_open' in text
    assert 'state: "{{ is_state(\'binary_sensor.any_window_open\', \'on\') }}"' in text
