from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.room_name_registry import (  # noqa: E402
    ROOM_NAME_SPECS,
    allowed_zigbee2mqtt_namespaces,
    resolve_room_key,
    specs_with_intent_keys,
)

ROOM_INTENT_PATH = ROOT / "docs" / "room_intent.yaml"
README_PATH = ROOT / "README.md"
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"
VALIDATE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "validate-config.yml"
Z2M_PATH = ROOT / "zigbee2mqtt" / "configuration.yaml"
OWNER_SUITE_TILE_PATH = ROOT / "lovelace" / "tiles" / "tiles_master_bedroom.yaml"
GUEST_ROOM_TILE_PATH = ROOT / "lovelace" / "tiles" / "tiles_guest_room.yaml"


def _room_intent_keys() -> set[str]:
    text = ROOM_INTENT_PATH.read_text(encoding="utf-8")
    match = re.search(r"^rooms:\n(?P<body>.*?)^decision_rules:\n", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError("Could not parse rooms block from docs/room_intent.yaml")
    return set(re.findall(r"^  ([a-z_]+):\n", match.group("body"), re.MULTILINE))


def _legacy_room_mapping() -> dict[str, str]:
    text = ROOM_INTENT_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^  legacy_room_mapping:\n(?P<body>.*?)(?=^  notes:\n)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError("Could not parse legacy_room_mapping block from docs/room_intent.yaml")
    return {
        source: replacement
        for source, replacement in re.findall(
            r"^    ([a-z_]+):\n      replacement: ([a-z_]+)\n",
            match.group("body"),
            re.MULTILINE,
        )
    }


def _zigbee2mqtt_prefixes() -> set[str]:
    text = Z2M_PATH.read_text(encoding="utf-8")
    prefixes: set[str] = set()
    for raw_value in re.findall(r"friendly_name:\s*([^\n]+)", text):
        value = raw_value.strip().strip('"')
        if "/" not in value:
            continue
        prefixes.add(value.split("/", 1)[0])
    return prefixes


def _vacuum_room_options() -> list[str]:
    text = VACUUM_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^  vacuum_room:\n    name: .*\n    options:\n(?P<body>(?:      - .*\n)+)",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise AssertionError("Could not parse input_select.vacuum_room options")
    return [line.removeprefix("      - ").strip() for line in match.group("body").splitlines()]


def test_room_name_registry_covers_room_intent_rooms() -> None:
    registered_intent_keys = {spec.intent_key for spec in specs_with_intent_keys()}
    assert _room_intent_keys() <= registered_intent_keys


def test_room_name_registry_covers_legacy_room_mapping() -> None:
    mapping = _legacy_room_mapping()
    assert mapping == {"living_room": "dining_room"}
    assert resolve_room_key("living_room") == "dining_room"
    assert resolve_room_key("Living Room") == "dining_room"
    assert resolve_room_key("Dining Room") == "dining_room"


def test_room_name_registry_covers_current_zigbee2mqtt_room_prefixes() -> None:
    assert _zigbee2mqtt_prefixes() <= allowed_zigbee2mqtt_namespaces()


def test_owner_suite_and_guest_room_tiles_use_preferred_names() -> None:
    owner_suite_text = OWNER_SUITE_TILE_PATH.read_text(encoding="utf-8")
    guest_room_text = GUEST_ROOM_TILE_PATH.read_text(encoding="utf-8")
    assert "Master Bedroom" not in owner_suite_text
    assert "Guest Bedroom" not in guest_room_text
    assert "Owner Suite Bedroom" in owner_suite_text
    assert "Guest Room" in guest_room_text


def test_vacuum_room_picker_uses_registered_room_names() -> None:
    options = _vacuum_room_options()
    assert options == [
        "Select Input",
        "Master Bedroom",
        "Guest Room",
        "Living Room",
        "Bathroom",
        "Hallway",
        "Kitchen",
        "Office",
    ]
    assert [resolve_room_key(option) for option in options[1:]] == [
        "owner_suite_bedroom",
        "guest_room",
        "dining_room",
        "bathroom",
        "hallway",
        "kitchen",
        "office",
    ]


def test_room_name_registry_is_documented_in_readme() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert "- [Room Naming Model](docs/room_names.md)" in text


def test_validate_config_workflow_runs_pytest_for_room_name_enforcement() -> None:
    text = VALIDATE_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "name: Pytest" in text
    assert "uv run --with pytest pytest" in text


def test_room_name_registry_keys_are_unique() -> None:
    keys = [spec.key for spec in ROOM_NAME_SPECS]
    assert len(keys) == len(set(keys))
