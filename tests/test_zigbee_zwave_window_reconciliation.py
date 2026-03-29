from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _customize_block(entity_id: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"    {entity_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find customize block for {entity_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("    ") and not lines[index].startswith("      "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_window_contact_entities_use_window_device_class_globally() -> None:
    text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    assert "customize_glob:" in text
    assert '"binary_sensor.*window*_contact":' in text
    assert '    "binary_sensor.*window*_contact":\n      <<: *customize\n      device_class: window' in text


def test_window_contact_entities_have_explicit_human_readable_names() -> None:
    expected_names = {
        "binary_sensor.basement_window_contact": "Basement Window",
        "binary_sensor.dining_room_north_window_contact": "Dining Room North Window",
        "binary_sensor.dining_room_south_window_contact": "Dining Room South Window",
        "binary_sensor.ene_window_contact": "East North East Window",
        "binary_sensor.ese_window_contact": "East South East Window",
        "binary_sensor.guest_bathroom_window_contact": "Guest Bathroom Window",
        "binary_sensor.guest_room_window_contact": "Guest Room Window",
        "binary_sensor.kitchen_bay_middle_window_contact": "Kitchen Bay Middle Window",
        "binary_sensor.kitchen_bay_north_window_contact": "Kitchen Bay North Window",
        "binary_sensor.kitchen_bay_south_window_contact": "Kitchen Bay South Window",
        "binary_sensor.kitchen_north_window_contact": "Kitchen North Window",
        "binary_sensor.kitchen_south_window_contact": "Kitchen South Window",
        "binary_sensor.nne_window_contact": "North North East Window",
        "binary_sensor.north_kitchen_sink_window_contact": "Kitchen Sink Window",
        "binary_sensor.north_master_bedroom_window_contact": "Master Bedroom Window",
        "binary_sensor.nw_basement_window_contact": "North West Basement Window",
        "binary_sensor.office_north_window_contact": "Office Window",
        "binary_sensor.office_window_contact": "Office Window",
        "binary_sensor.owner_suite_bathroom_bay_north_middle_window_contact": "Owner Suite Bathroom Bay North Middle Window",
        "binary_sensor.owner_suite_bathroom_bay_north_window_contact": "Owner Suite Bathroom Bay North Window",
        "binary_sensor.owner_suite_bathroom_bay_south_middle_window_contact": "Owner Suite Bathroom Bay South Middle Window",
        "binary_sensor.owner_suite_bathroom_bay_south_window_contact": "Owner Suite Bathroom Bay South Window",
        "binary_sensor.owner_suite_north_window_contact": "Owner Suite North Window",
        "binary_sensor.owner_suite_south_window_contact": "Owner Suite South Window",
        "binary_sensor.powder_room_window_contact": "Powder Room Window",
        "binary_sensor.se_basement_window_contact": "South East Basement Window",
        "binary_sensor.sse_window_contact": "South South East Living Room Window",
        "binary_sensor.sw_basement_window_contact": "South West Basement Window",
        "binary_sensor.unfinished_basement_window_contact": "Unfinished Basement Window",
    }

    for entity_id, friendly_name in expected_names.items():
        block = _customize_block(entity_id)

        assert "device_class: window" in block
        assert f'friendly_name: "{friendly_name}"' in block
