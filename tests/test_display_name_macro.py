from __future__ import annotations

from pathlib import Path

import jinja2
import pytest


ROOT = Path(__file__).resolve().parents[1]

# entity_id: (entity_name(), device_name(), area_name()) as Home Assistant
# 2026.11 returns them. entity_name() is "" for a device's main entity.
REGISTRY: dict[str, tuple[str | None, str | None, str | None]] = {
    # Window contacts before the issue #1175 rename: legacy full entity names.
    "binary_sensor.kitchen_north_window_contact": (
        "Kitchen North Window",
        "Kitchen/North Window",
        "Kitchen",
    ),
    "binary_sensor.owner_suite_south_window_contact": (
        "Owner Suite South Window",
        "Owner Suite/South Window",
        "Owner Suite Bedroom",
    ),
    "binary_sensor.basement_window_contact": (
        "Basement Window",
        "Basement/Window",
        "Basement Great Room",
    ),
    # The same windows after the rename: main entity of a room-free device.
    "binary_sensor.renamed_kitchen_north_window": ("", "North Window", "Kitchen"),
    "binary_sensor.renamed_owner_suite_south_window": (
        "",
        "South Window",
        "Owner Suite Bedroom",
    ),
    "binary_sensor.renamed_dining_room_north_window": ("", "North Window", "Dining Room"),
    # Doors that are already main entities of Zigbee2MQTT-named devices.
    "binary_sensor.main_foyer_front_door_contact": ("", "Main Foyer/Front Door", "Hallway"),
    "binary_sensor.hall_garage_entry_contact": ("", "Hall/Garage Entry", "Hallway"),
    # Ordinary device + entity composition.
    "binary_sensor.refrigerator_door": ("Door", "Refrigerator", "Kitchen"),
    "sensor.north_window_battery": ("Battery", "North Window", "Kitchen"),
    # Entity names that repeat the device name.
    "sensor.kitchen_north_window_battery": (
        "Kitchen/North Window Battery",
        "Kitchen/North Window",
        "Kitchen",
    ),
    # No device, no area.
    "binary_sensor.any_window_open": ("Any window open", None, None),
    # Nothing registered at all.
    "binary_sensor.unregistered": (None, None, None),
}


def _render(entity_id: str) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROOT / "custom_templates"),
        undefined=jinja2.StrictUndefined,
    )
    env.globals["entity_name"] = lambda e: REGISTRY[e][0]
    env.globals["device_name"] = lambda e: REGISTRY[e][1]
    env.globals["area_name"] = lambda e: REGISTRY[e][2]
    template = env.from_string(
        "{% from 'display_name.jinja' import contextual_name %}"
        "{{ contextual_name(entity_id) }}"
    )
    return template.render(entity_id=entity_id)


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("binary_sensor.kitchen_north_window_contact", "Kitchen North Window"),
        ("binary_sensor.owner_suite_south_window_contact", "Owner Suite South Window"),
        ("binary_sensor.basement_window_contact", "Basement Window"),
        ("binary_sensor.renamed_kitchen_north_window", "Kitchen North Window"),
        (
            "binary_sensor.renamed_owner_suite_south_window",
            "Owner Suite Bedroom South Window",
        ),
        ("binary_sensor.renamed_dining_room_north_window", "Dining Room North Window"),
        ("binary_sensor.main_foyer_front_door_contact", "Main Foyer Front Door"),
        ("binary_sensor.hall_garage_entry_contact", "Hall Garage Entry"),
        ("binary_sensor.refrigerator_door", "Kitchen Refrigerator Door"),
        ("sensor.north_window_battery", "Kitchen North Window Battery"),
        ("sensor.kitchen_north_window_battery", "Kitchen North Window Battery"),
        ("binary_sensor.any_window_open", "Any window open"),
        ("binary_sensor.unregistered", "binary_sensor.unregistered"),
    ],
)
def test_contextual_name(entity_id: str, expected: str) -> None:
    assert _render(entity_id) == expected


def test_two_rooms_sharing_a_fixture_name_stay_distinct() -> None:
    names = {
        _render("binary_sensor.renamed_kitchen_north_window"),
        _render("binary_sensor.renamed_dining_room_north_window"),
    }

    assert names == {"Kitchen North Window", "Dining Room North Window"}


def test_macro_does_not_read_friendly_name() -> None:
    text = (ROOT / "custom_templates/display_name.jinja").read_text(encoding="utf-8")
    body = text.split("-#}", 1)[1]

    assert "friendly_name" not in body
