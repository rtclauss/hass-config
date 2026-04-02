from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoomNameSpec:
    key: str
    preferred_label: str
    home_assistant_area: str
    intent_key: str | None = None
    zigbee2mqtt_namespaces: tuple[str, ...] = ()
    legacy_labels: tuple[str, ...] = ()
    notes: str = ""

    @property
    def all_labels(self) -> tuple[str, ...]:
        return (self.preferred_label, *self.legacy_labels)


ROOM_NAME_SPECS: tuple[RoomNameSpec, ...] = (
    RoomNameSpec(
        key="owner_suite_bedroom",
        preferred_label="Owner Suite Bedroom",
        home_assistant_area="Bedroom",
        intent_key="owner_suite_bedroom",
        zigbee2mqtt_namespaces=("Owner Suite",),
        legacy_labels=("Master Bedroom", "Bedroom"),
        notes="Keep the Owner Suite Zigbee2MQTT namespace stable until a dedicated safe-refactor updates every consumer.",
    ),
    RoomNameSpec(
        key="owner_suite_bathroom",
        preferred_label="Owner Suite Bathroom",
        home_assistant_area="Owner Suite Bathroom",
        intent_key="owner_suite_bathroom",
    ),
    RoomNameSpec(
        key="office",
        preferred_label="Office",
        home_assistant_area="Office",
        intent_key="office",
        zigbee2mqtt_namespaces=("Office",),
    ),
    RoomNameSpec(
        key="den",
        preferred_label="Den",
        home_assistant_area="Den",
        intent_key="den",
        zigbee2mqtt_namespaces=("Den",),
    ),
    RoomNameSpec(
        key="guest_room",
        preferred_label="Guest Room",
        home_assistant_area="Guest Room",
        intent_key="guest_room",
        zigbee2mqtt_namespaces=("Guest Room",),
        legacy_labels=("Guest Bedroom",),
    ),
    RoomNameSpec(
        key="guest_bathroom",
        preferred_label="Guest Bathroom",
        home_assistant_area="Guest Bathroom",
        intent_key="guest_bathroom",
        zigbee2mqtt_namespaces=("Guest Bathroom",),
    ),
    RoomNameSpec(
        key="bathroom",
        preferred_label="Bathroom",
        home_assistant_area="Bathroom",
        zigbee2mqtt_namespaces=("Bathroom",),
    ),
    RoomNameSpec(
        key="basement_great_room",
        preferred_label="Basement Great Room",
        home_assistant_area="Basement Great Room",
        intent_key="basement_great_room",
        zigbee2mqtt_namespaces=("Basement",),
        legacy_labels=("Basement",),
        notes="The live Zigbee2MQTT namespace is still the shorter Basement prefix.",
    ),
    RoomNameSpec(
        key="kitchen",
        preferred_label="Kitchen",
        home_assistant_area="Kitchen",
        intent_key="kitchen",
        zigbee2mqtt_namespaces=("Kitchen",),
    ),
    RoomNameSpec(
        key="outside",
        preferred_label="Outside",
        home_assistant_area="Outside",
        intent_key="outside",
        zigbee2mqtt_namespaces=("Outside",),
    ),
    RoomNameSpec(
        key="dining_room",
        preferred_label="Dining Room",
        home_assistant_area="Dining Room",
        intent_key="dining_room",
        zigbee2mqtt_namespaces=("Dining Room", "Living Room"),
        legacy_labels=("Living Room",),
        notes="Living Room remains an allowed legacy label until the dining-room migration can safely update all live entity names.",
    ),
    RoomNameSpec(
        key="hallway",
        preferred_label="Hallway",
        home_assistant_area="Hallway",
        zigbee2mqtt_namespaces=("Hall",),
        legacy_labels=("Hall",),
    ),
    RoomNameSpec(
        key="main_foyer",
        preferred_label="Main Foyer",
        home_assistant_area="Main Foyer",
        zigbee2mqtt_namespaces=("Main Foyer",),
    ),
    RoomNameSpec(
        key="laundry_room",
        preferred_label="Laundry Room",
        home_assistant_area="Laundry Room",
        zigbee2mqtt_namespaces=("Laundry", "Laundry Room"),
        legacy_labels=("Laundry",),
        notes="Laundry remains a valid live device namespace, but new UI labels should use Laundry Room.",
    ),
    RoomNameSpec(
        key="garage",
        preferred_label="Garage",
        home_assistant_area="Garage",
        zigbee2mqtt_namespaces=("Garage",),
    ),
    RoomNameSpec(
        key="deck",
        preferred_label="Deck",
        home_assistant_area="Deck",
        zigbee2mqtt_namespaces=("Deck",),
    ),
    RoomNameSpec(
        key="powder_room",
        preferred_label="Powder Room",
        home_assistant_area="Powder Room",
        zigbee2mqtt_namespaces=("Powder Room",),
    ),
    RoomNameSpec(
        key="tiki_room",
        preferred_label="Tiki Room",
        home_assistant_area="Tiki Room",
        zigbee2mqtt_namespaces=("Tiki Room",),
    ),
    RoomNameSpec(
        key="unfinished_basement",
        preferred_label="Unfinished Basement",
        home_assistant_area="Unfinished Basement",
        zigbee2mqtt_namespaces=("Unfinished Basement",),
    ),
)


ROOM_NAME_SPECS_BY_KEY = {spec.key: spec for spec in ROOM_NAME_SPECS}


def specs_with_intent_keys() -> tuple[RoomNameSpec, ...]:
    return tuple(spec for spec in ROOM_NAME_SPECS if spec.intent_key is not None)


def allowed_room_labels() -> set[str]:
    return {label for spec in ROOM_NAME_SPECS for label in spec.all_labels}


def allowed_zigbee2mqtt_namespaces() -> set[str]:
    return {name for spec in ROOM_NAME_SPECS for name in spec.zigbee2mqtt_namespaces}


def resolve_room_key(label: str) -> str:
    normalized_label = label.replace("_", " ").lower()
    for spec in ROOM_NAME_SPECS:
        if normalized_label in {
            spec.key.replace("_", " ").lower(),
            (spec.intent_key or "").replace("_", " ").lower(),
        }:
            return spec.key
        if normalized_label in {value.lower() for value in spec.all_labels}:
            return spec.key
        if normalized_label in {value.lower() for value in spec.zigbee2mqtt_namespaces}:
            return spec.key
    raise KeyError(label)
