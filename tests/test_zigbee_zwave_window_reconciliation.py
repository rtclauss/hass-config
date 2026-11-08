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


def test_window_contact_names_come_from_the_registry_not_customize() -> None:
    # Issue #1175: Home Assistant 2026.11 owns display names in the registry
    # (device "North Window" in area "Kitchen", contact as the main entity).
    # A customize friendly_name would mask that and is slated for deprecation;
    # whole-home text composes the room via custom_templates/display_name.jinja.
    window_contacts = (
        "binary_sensor.basement_window_contact",
        "binary_sensor.dining_room_north_window_contact",
        "binary_sensor.dining_room_south_window_contact",
        "binary_sensor.guest_bathroom_window_contact",
        "binary_sensor.guest_room_window_contact",
        "binary_sensor.kitchen_bay_middle_window_contact",
        "binary_sensor.kitchen_bay_north_window_contact",
        "binary_sensor.kitchen_bay_south_window_contact",
        "binary_sensor.kitchen_north_window_contact",
        "binary_sensor.kitchen_south_window_contact",
        "binary_sensor.office_window_contact",
        "binary_sensor.owner_suite_bathroom_bay_north_middle_window_contact",
        "binary_sensor.owner_suite_bathroom_bay_north_window_contact",
        "binary_sensor.owner_suite_bathroom_bay_south_middle_window_contact",
        "binary_sensor.owner_suite_bathroom_bay_south_window_contact",
        "binary_sensor.owner_suite_north_window_contact",
        "binary_sensor.owner_suite_south_window_contact",
        "binary_sensor.powder_room_window_contact",
        "binary_sensor.unfinished_basement_window_contact",
    )

    for entity_id in window_contacts:
        block = _customize_block(entity_id)

        assert "device_class: window" in block
        assert "friendly_name" not in block


def test_whole_home_window_and_egress_lists_use_contextual_names() -> None:
    root = Path(__file__).resolve().parents[1]
    climate = (root / "private_templates/climate.yaml.tmpl").read_text(encoding="utf-8")
    zigbee = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    assert "[contextual_name(entity_id)]" in climate
    assert "[sensor.name]" not in climate
    assert "{% from 'display_name.jinja' import contextual_name %}" in zigbee
    assert "ns.names + [contextual_name(entity_id)]" in zigbee
    assert "ns.names + [entity_name(entity_id)]" not in zigbee
