"""Compose UI-editable Lovelace changes without losing unrelated dashboard data.

Input/output may contain private runtime configuration. Keep real exports outside
Git; use the existing synthetic fixture for public examples. Applying is done via
the HA dashboard API with its configuration-hash precondition, never .storage.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

READINESS = (
    ("security", "Security"), ("climate", "Temperature"), ("water", "Water supply"),
    ("vacuum_main", "Main floor vacuum"), ("mop_main", "Main floor mop"),
    ("vacuum_den", "Den vacuum"), ("vacuum_upstairs", "Upstairs vacuum"),
    ("pet_care", "Pet care"),
)
ROOMS = (
    ("Owner suite", "mdi:bed-king-outline", "light.owner_suite_lamps", "owner-suite"),
    ("Office", "mdi:desk", "light.office_all", "office-v2"),
    ("Kitchen", "mdi:countertop-outline", "light.kitchen_all", "main-floor"),
    ("Den", "mdi:sofa-outline", "light.den_all", "main-floor"),
    ("Dining room", "mdi:table-furniture", "light.dining_room_all", "main-floor"),
    ("Hallway", "mdi:door-open", "light.hall_all", "main-floor"),
    ("Basement", "mdi:television", "light.all_basement_lights", "basement-v2"),
    ("Guest room", "mdi:bed-outline", "light.guest_room_ceiling", "upstairs"),
    ("Deck", "mdi:outdoor-lamp", "light.deck_all", "outside"),
)
DAILY = {"owner-suite", "office-v2", "main-floor", "basement-v2", "upstairs", "outside", "media-players", "climate", "cleaning-v2", "deliveries"}
PRIMARY = {"home", "rooms", "house", "travel", "more"}


def tile(entity: str, name: str | None = None, features: tuple[str, ...] = ()) -> dict:
    card: dict[str, Any] = {"type": "tile", "entity": entity, "grid_options": {"columns": 6}, "tap_action": {"action": "more-info"}}
    if name:
        card["name"] = name
    if features:
        card["features"] = [{"type": feature} for feature in features]
        if "fan-speed" in features:
            card["grid_options"]["columns"] = 12
    return card


def shortcut(name: str, path: str, icon: str = "mdi:arrow-right") -> dict:
    return {"type": "shortcut", "label": name, "icon": icon,
            "tap_action": {"action": "navigate", "navigation_path": path},
            "grid_options": {"columns": 6}}


def heading(text: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title"}


def section(title: str, cards: list[dict], span: int = 1) -> dict:
    return {"type": "grid", "column_span": span, "cards": ([heading(title)] if title else []) + cards}


def navigation(root: str) -> dict:
    # A single factory keeps editor-visible nav configurations identical.
    return {"type": "custom:navbar-card",
            "routes": [{"url": f"{root}/{slug}", "label": label, "icon": icon}
                       for slug, label, icon in [("home", "Home", "mdi:home-outline"),
                           ("rooms", "Rooms", "mdi:view-grid-outline"),
                           ("house", "House", "mdi:tune-variant"),
                           ("travel", "Travel", "mdi:airplane"),
                           ("more", "More", "mdi:dots-horizontal")]],
            "desktop": {"min_width": 1200, "position": "left", "show_labels": True},
            "mobile": {"show_labels": True, "safe_area": True},
            "layout": {"auto_padding": {"enabled": True}, "reflect_child_state": True}}


def room_card(room: tuple[str, str, str, str], root: str) -> dict:
    name, icon, entity, path = room
    action = {"action": "navigate", "navigation_path": f"{root}/{path}"}
    return {"type": "tile", "entity": entity, "name": name, "icon": icon,
            "vertical": True, "tap_action": action, "icon_tap_action": deepcopy(action),
            "grid_options": {"columns": 6, "rows": 2}}


def normalize_card(value: Any) -> Any:
    """Modernize known light/fan/cover cards; retain specialist capabilities."""
    if isinstance(value, list):
        return [normalize_card(item) for item in value]
    if not isinstance(value, dict):
        return value
    card = {key: normalize_card(item) for key, item in value.items()}
    kind = card.get("type")
    entity = card.get("entity")
    features: list[str] = []
    if kind == "custom:mushroom-light-card" and entity:
        if card.get("show_brightness_control"):
            features.append("light-brightness")
        if card.get("show_color_temp_control"):
            features.append("light-color-temp")
    elif kind == "custom:mushroom-fan-card" and entity:
        if card.get("show_percentage_control"):
            features.append("fan-speed")
    elif kind == "custom:mushroom-cover-card" and entity:
        if card.get("show_position_control"):
            features.append("cover-position")
    else:
        if kind == "horizontal-stack":
            has_fan = any(any(f.get("type") == "fan-speed" for f in c.get("features", []))
                          for c in card.get("cards", []))
            card.update(type="grid", columns=1 if has_fan else min(2, max(1, len(card.get("cards", [])))), square=False)
        return card
    result = tile(entity, card.get("name"), tuple(features))
    # Preserve deliberate actions, including navigation and confirmation.
    for key in ("tap_action", "hold_action", "double_tap_action", "visibility"):
        if key in card:
            result[key] = card[key]
    return result


def decorate(view: dict, root: str, parent: str) -> dict:
    view["theme"] = "Calm Home"
    # Keep native keyboard-accessible tabs for the five primary destinations.
    view["subview"] = view.get("path") not in PRIMARY
    if view["subview"]:
        view["back_path"] = f"{root}/{parent}"
    if view.get("type") == "sections":
        view["max_columns"] = 4
        view["dense_section_placement"] = False
        view["footer"] = {"card": navigation(root)}
    else:
        # Legacy specialist cards stay intact; only add navigation.
        cards = view.setdefault("cards", [])
        cards[:] = [c for c in cards if c.get("type") != "custom:navbar-card"]
        cards.append(navigation(root))
    return view


def view(title: str, path: str, sections: list[dict], root: str) -> dict:
    # Native Sections handles reflow. No CSS layout or extra layout-card dependency.
    first = sections[0]
    first["column_span"] = 4
    first["cards"] = [{"type": "vertical-stack", "grid_options": {"columns": "full"}, "cards": first["cards"]}]
    return decorate({"title": title, "path": path, "type": "sections", "max_columns": 4,
                     "sections": sections}, root, "home")


def build_dashboard(existing: dict, root: str, states: dict[str, dict] | None = None) -> dict:
    if not root.startswith("/") or root.endswith("/"):
        raise ValueError("root must be an absolute dashboard path without a trailing slash")
    result = deepcopy(existing)
    if not result.get("views"):
        raise ValueError("existing dashboard must contain views")
    if result["views"][0].get("title") != "Home" and result["views"][0].get("path") != "home":
        raise ValueError("first view must be Home; refusing to replace an unrelated view")
    states = states or {}
    result["background"] = "var(--primary-background-color)"
    templates = result.setdefault("button_card_templates", {})
    templates.pop("calm_room", None)  # Superseded by native keyboard-accessible tiles.
    templates["calm_readiness"] = {
        "show_name": True, "show_state": True, "show_label": True, "size": "22px",
        "icon": "mdi:progress-check",
        "label": "[[[ const a = entity?.attributes || {}; const d = new Date(a.evidence_at); const when = a.evidence_at && !isNaN(d) ? new Intl.DateTimeFormat(undefined, {month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:hass.config.time_zone,timeZoneName:'short'}).format(d) : ''; return (a.reason || 'Evidence unavailable') + (when ? ' · Evidence: ' + when : ''); ]]]",
        "tap_action": {"action": "more-info"},
        "styles": {"card": [{"border-radius": "16px"}, {"padding": "16px"}, {"min-height": "110px"}, {"box-shadow": "none"}],
                   "grid": [{"grid-template-areas": '"i n s" ". l l"'}, {"grid-template-columns": "30px 1fr auto"}],
                   "name": [{"justify-self": "start"}, {"font-size": "14px"}, {"font-weight": "500"}],
                   "state": [{"font-size": "12px"}],
                   "label": [{"white-space": "normal"}, {"text-align": "left"}, {"font-size": "13px"}, {"line-height": "1.5"}, {"padding-top": "8px"}, {"color": "var(--secondary-text-color)"}]},
        "state": [{"value": "blocked", "icon": "mdi:alert-circle-outline", "color": "var(--error-color)"},
                  {"value": "unknown", "icon": "mdi:help-circle-outline", "color": "var(--secondary-text-color)"},
                  {"value": "complete", "icon": "mdi:check-circle-outline", "color": "var(--primary-color)"}],
    }
    readiness = [{"type": "custom:button-card", "template": "calm_readiness",
                  "entity": f"sensor.dashboard_readiness_{key}", "name": name,
                  "grid_options": {"columns": "full"}} for key, name in READINESS]
    context_card = {"type": "markdown", "text_only": True,
        "entity_id": ["sensor.dashboard_context", "input_select.house_mode", "input_boolean.trip"],
        "content": "{% set c = states('sensor.dashboard_context') %}\n# {{ {'home': 'Your home, at a glance', 'morning': 'A clear start to the day', 'evening': 'A quiet evening', 'sleep': 'Keeping things quiet', 'departure': 'Ready to leave?', 'away': 'A clear view of home', 'return': 'Home is getting ready'}.get(c, 'Home status needs a look') }}\n{{ {'return': 'Check actual arrival-readiness results below.', 'away': 'Security, pet care, temperature, and water.', 'departure': 'Review the house before your trip.', 'sleep': 'Your controls stay available when you need them.'}.get(c, 'Room groups first. Details when you need them.') }}"}
    context_cards = [context_card, shortcut("Travel and readiness", f"{root}/travel", "mdi:airplane-check")]
    context_cards[-1]["visibility"] = [{"condition": "state", "entity": "sensor.dashboard_context", "state": ["return", "away", "departure"]}]
    favorites = [tile("light.owner_suite_lamps", "Lamps", ("light-brightness",)),
                 tile("fan.owner_suite", "Ceiling fan", ("fan-speed",)),
                 tile("cover.owner_suite_blinds_ha", "Blinds", ("cover-position",)),
                 tile("light.owner_suite_bathroom_lights_2", "Bathroom lights", ("light-brightness",)),
                 tile("media_player.ma_bedroom", "Bedroom audio", ("media-player-playback", "media-player-volume-slider")),
                 shortcut("Alarms", f"{root}/owner-suite", "mdi:alarm")]
    exceptions = []
    for key, label in READINESS:
        card = tile(f"sensor.dashboard_readiness_{key}", label)
        card["visibility"] = [{"condition": "state", "entity": card["entity"],
                               "state": ["blocked", "unknown"] if key in {"security", "water"} else "blocked"}]
        exceptions.append(card)
    for entity, label in [("binary_sensor.washing_machine_running", "Washer running"), ("binary_sensor.dryer_running", "Dryer running"), ("input_boolean.mail_delivered", "Delivery waiting")]:
        card = tile(entity, label)
        card["visibility"] = [{"condition": "state", "entity": entity, "state": "on"}]
        exceptions.append(card)
    for entity in ["fan.owner_suite", "light.owner_suite_lamps", "cover.owner_suite_blinds_ha", "media_player.ma_bedroom"]:
        card = tile(entity)
        card["visibility"] = [{"condition": "state", "entity": entity, "state": ["unavailable", "unknown"]}]
        exceptions.append(card)
    home = view("Home", "home", [section("", context_cards),
        section("Often used", favorites, 2), section("Your rooms", [room_card(r, root) for r in ROOMS[:4]], 2),
        section("Needs attention", exceptions, 2),
        section("House status", [tile("input_select.house_mode", "House mode"), tile("input_boolean.guest_mode", "Guest mode"), tile("climate.my_ecobee", "Temperature"), tile("weather.tomorrow_io_the_brewery_daily", "Weather")], 2)], root)
    home["sections"][3]["visibility"] = [{"condition": "or", "conditions": [card["visibility"][0] for card in exceptions]}]
    rooms = view("Rooms", "rooms", [section("Rooms", [{"type": "markdown", "text_only": True, "content": "Control a room together. Open its details for individual devices."}]),
        section("Upstairs", [room_card(r, root) for r in (ROOMS[0], ROOMS[1], ROOMS[7])], 2),
        section("Main floor", [room_card(r, root) for r in ROOMS[2:6]], 2),
        section("Other spaces", [room_card(r, root) for r in (ROOMS[6], ROOMS[8])], 2)], root)
    lights = [tile(entity, name, ("light-brightness",)) for name, _, entity, _ in ROOMS
              if not states or entity in states]
    house = view("House", "house", [section("Whole house", [shortcut("Climate details", f"{root}/climate", "mdi:thermostat"), shortcut("Media and groups", f"{root}/media-players", "mdi:speaker-multiple")]),
        section("Room light groups", lights, 2),
        section("Comfort", [tile("climate.my_ecobee", "Thermostat", ("target-temperature",)), shortcut("Climate", f"{root}/climate")], 2),
        section("Household", [shortcut("Cleaning and laundry", f"{root}/cleaning-v2", "mdi:robot-vacuum"), shortcut("Deliveries", f"{root}/deliveries", "mdi:package-variant"), {"type": "todo-list", "entity": "todo.shopping_list"}], 2)], root)
    travel = view("Travel", "travel", [section("Travel", [tile("input_boolean.trip", "Trip mode"), tile("input_boolean.trip_guest_visit_active", "Guest visit"), {"type": "markdown", "text_only": True, "entity_id": ["sensor.dashboard_return_cycle", "sensor.dashboard_context"], "content": "{% set landing = state_attr('sensor.dashboard_return_cycle', 'landing_at') %}\n{{ 'Flight landing: ' ~ (as_datetime(landing) | as_local).strftime('%a %-I:%M %p %Z') if landing else 'No current return flight is associated.' }}\n\nWater restoration follows the existing trip-end flow. Completion below requires evidence; docking and launch attempts are not proof."}]),
        section("Security and water", [tile("alarm_control_panel.home_alarm", "Alarm"), tile("lock.front_door_lock", "Front door"), tile("cover.garage_door", "Garage"), tile("switch.basement_water_shutoff", "Water supply")], 2),
        section("Arrival readiness", readiness, 2),
        section("Pet care", [tile("binary_sensor.main_level_cat_feeder_error", "Main-floor feeder"), tile("binary_sensor.upstairs_cat_feeder_error", "Upstairs feeder"), tile("select.main_level_cat_feeder_mode", "Main-floor schedule"), tile("select.upstairs_cat_feeder_mode", "Upstairs schedule")], 2),
        section("Cameras · open on demand", [tile(e, n) for e, n in [("camera.front_door", "Front entrance"), ("camera.livingroomcamera", "Dining room"), ("camera.tikiroomcamera", "Tiki room")] if not states or e in states], 2)], root)
    # Supply-altering controls are explicit and confirmed; no contextual action runs automatically.
    for card in travel["sections"][1]["cards"]:
        if card.get("entity") in {"lock.front_door_lock", "cover.garage_door", "switch.basement_water_shutoff"}:
            card["icon_tap_action"] = {"action": "more-info"}
            card["hold_action"] = {"action": "more-info"}
    originals = result["views"]
    more_links = [shortcut(v.get("title", "Details"), f"{root}/{v.get('path', i)}", v.get("icon", "mdi:view-dashboard-outline"))
                  for i, v in enumerate(originals) if i and v.get("path") not in PRIMARY]
    more = view("More", "more", [section("More", [shortcut("Security dashboard", "/security", "mdi:shield-home-outline"), shortcut("Flight Deck", "/flight-deck", "mdi:airplane-clock")]), section("Specialist views", more_links, 2)], root)
    # Keep every original index and path, including legacy numeric deep links.
    originals[0] = home
    for old in originals[1:]:
        path = old.get("path", "")
        if path in PRIMARY:
            continue
        if path in DAILY:
            upgraded = normalize_card(old)
            old.clear()
            old.update(upgraded)
        decorate(old, root, "rooms" if path in DAILY else "more")
    additions = {"rooms": rooms, "house": house, "travel": travel, "more": more}
    for slug, new in additions.items():
        found = next((i for i, old in enumerate(originals) if old.get("path") == slug), None)
        if found is None:
            originals.append(new)
        else:
            originals[found] = new
    return result


def entity_references(value: Any) -> set[str]:
    """Card entities, including group variables and explicit targets."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"entity", "entity_id"}:
                values = item if isinstance(item, list) else [item]
                found.update(v for v in values if isinstance(v, str) and "." in v and " " not in v and "{{" not in v)
            found.update(entity_references(item))
    elif isinstance(value, list):
        for item in value:
            found.update(entity_references(item))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--states", type=Path)
    args = parser.parse_args()
    existing = json.loads(args.input.read_text())
    wrapped = "data" in existing and "config" in existing["data"]
    config = existing["data"]["config"] if wrapped else existing
    inventory = {s["entity_id"]: s for s in json.loads(args.states.read_text())} if args.states else None
    rebuilt = build_dashboard(config, args.root, inventory)
    if wrapped:
        existing["data"]["config"] = rebuilt
        rebuilt = existing
    args.output.write_text(json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n")
    args.output.chmod(0o600)


if __name__ == "__main__":
    main()
