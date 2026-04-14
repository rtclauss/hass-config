from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / ".storage" / "lovelace.ryan_new_mushroom"


def _dashboard_config() -> dict:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    return dashboard["data"]["config"]


def _find_dashboard_section_cards(config: dict, *, heading: str) -> list[dict]:
    for view in config["views"]:
        cards = _find_view_section_cards(view, heading=heading)
        if cards is not None:
            return cards
    raise AssertionError(f"Could not find section with heading {heading!r}")


def _find_view_section_cards(view: dict, *, heading: str) -> list[dict] | None:
    for section in view.get("sections", []):
        cards = section.get("cards", [])
        if any(card.get("heading") == heading for card in cards):
            return cards
    return None


def _find_cleaning_card(config: dict, *, primary: str) -> dict:
    cleaning_view = next(
        (view for view in config["views"] if view.get("title") == "Cleaning-v2"),
        None,
    )
    assert cleaning_view is not None, "Cleaning-v2 view should exist"

    clothes_cards = _find_view_section_cards(cleaning_view, heading="Clothes")
    assert clothes_cards is not None, "Cleaning-v2 should expose a Clothes section"
    for card in clothes_cards:
        if card.get("primary") == primary:
            return card
    raise AssertionError(f"Could not find {primary!r} card in Cleaning-v2")


def test_main_floor_laundry_room_cards_use_running_binary_sensors() -> None:
    config = _dashboard_config()
    laundry_cards = _find_dashboard_section_cards(config, heading="Laundry Room")

    entities_card = next(card for card in laundry_cards if card.get("type") == "entities")
    assert [entry["entity"] for entry in entities_card["entities"]] == [
        "binary_sensor.washing_machine_running",
        "binary_sensor.dryer_running",
    ]

    chips_card = next(
        card for card in laundry_cards if card.get("type") == "custom:mushroom-chips-card"
    )
    assert [(chip["entity"], chip["name"], chip["icon"]) for chip in chips_card["chips"]] == [
        ("binary_sensor.washing_machine_running", "Washer", "mdi:washing-machine"),
        ("binary_sensor.dryer_running", "Dryer", "mdi:tumble-dryer"),
    ]


def test_cleaning_view_clothes_cards_use_power_based_binary_sensors() -> None:
    config = _dashboard_config()

    washer_card = _find_cleaning_card(config, primary="Washer")
    assert washer_card["entity"] == "binary_sensor.washing_machine_running"
    assert "sensor.laundry_room_washing_machine_power" in washer_card["secondary"]
    assert "sensor.laundry_room_washing_machine_current" in washer_card["secondary"]
    assert "sensor.front_load_washer" not in washer_card["secondary"]
    assert "binary_sensor.washing_machine_running" in washer_card["icon_color"]

    dryer_card = _find_cleaning_card(config, primary="Dryer")
    assert dryer_card["entity"] == "binary_sensor.dryer_running"
    assert "sensor.laundry_room_dryer_power" in dryer_card["secondary"]
    assert "sensor.laundry_room_dryer_current" in dryer_card["secondary"]
    assert 'is_state("sensor.dryer"' not in dryer_card["secondary"]
    assert "binary_sensor.dryer_running" in dryer_card["icon_color"]
