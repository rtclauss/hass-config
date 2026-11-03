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
MARKDOWN_TYPOGRAPHY = """
h1 { font-size: var(--calm-title-font-size, 29px) !important; font-weight: var(--calm-title-font-weight, 500) !important; letter-spacing: -.7px; margin: 8px 0 !important; line-height: 1.2 !important; }
h2, h3 { font-weight: var(--calm-title-font-weight, 500) !important; }
h3 { font-size: 14px !important; margin: 10px 12px !important; }
p { color: var(--secondary-text-color); font-size: 13px; line-height: 1.5; }
small { color: var(--secondary-text-color); font-size: 11px; letter-spacing: .06em; }
"""


def apply_typography(value: Any) -> None:
    """Shared JSON style avoids card-mod's theme-YAML editor-loader dependency."""
    if isinstance(value, list):
        for child in value:
            apply_typography(child)
    elif isinstance(value, dict):
        if value.get("type") == "markdown":
            value.setdefault("card_mod", {})["style"] = {"ha-markdown$": MARKDOWN_TYPOGRAPHY}
        for key, child in value.items():
            if key != "card_mod":
                apply_typography(child)


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
            "styles": """
              .navbar.desktop.left { top: 72px; transform: none; }
              .navbar-card.desktop { background: transparent; border: 0; box-shadow: none; }
              .desktop .route { width: 140px; height: 48px; flex-direction: row; gap: 10px; }
              .desktop .route .button { flex: 0 0 44px; width: 44px; height: 44px; }
              .desktop .route .label { text-align: left; flex: 1; font-size: 13px; }
              .desktop .route.active { background: var(--secondary-background-color); border-radius: 12px; }
              .desktop .button.active { background: transparent; }
            """,
            "layout": {"auto_padding": {"enabled": True, "desktop_px": 184}, "reflect_child_state": True}}


def room_card(room: tuple[str, str, str, str], root: str) -> dict:
    name, icon, entity, path = room
    action = {"action": "navigate", "navigation_path": f"{root}/{path}"}
    temperature = {"owner-suite": "sensor.bedroom_temperature_2", "office-v2": "sensor.office_temperature_2"}.get(path)
    if name == "Den":
        temperature = "sensor.den_temperature_2"
    summary = "{% set s = states(entity) %}{{ 'Lighting on' if s == 'on' else 'Lights off' if s == 'off' else 'Lighting unavailable' }}"
    if path == "owner-suite":
        summary = "{% set s = states(entity) %}{% set b = state_attr(entity, 'brightness') | float(none) %}{{ 'Lamps ' ~ ((b / 255 * 100) | round(0) | int) ~ '%' if s == 'on' and b is not none else 'Lamps on' if s == 'on' else 'Lamps off' if s == 'off' else 'Lamps unavailable' }} · Blinds {{ states('cover.owner_suite_blinds_ha') }}"
    if temperature:
        summary += "{% set t = states('" + temperature + "') | float(none) %}{% if t is not none %} · {{ t | round(0) | int }}°{% endif %}"
    result = summary_card(entity, name, icon, summary, "room", vertical=True)
    result.update(tap_action=action)
    result["color"] = "{{ 'primary' if is_state(entity, 'on') else 'secondary-text' }}"
    return result


def summary_card(entity: str, title: str, icon: str, detail: str, kind: str = "row", *, vertical: bool = False) -> dict:
    """Installed Mushroom Template uses native Tile semantics, including focus."""
    return {"type": "custom:mushroom-template-card", "entity": entity,
            "primary": title, "secondary": detail, "icon": icon,
            "color": "primary", "vertical": vertical, "multiline_secondary": True,
            "tap_action": {"action": "more-info"}, "icon_tap_action": {"action": "none"},
            "card_mod": {"class": f"calm-{kind}"},
            "grid_options": {"columns": "full", "rows": "auto"}}


def two_columns(cards: list[dict]) -> dict:
    # A native inner grid keeps rooms two-up on desktop and phone alike.
    return {"type": "grid", "columns": 2, "square": False, "cards": cards,
            "grid_options": {"columns": "full", "rows": "auto"}}


def panel(cards: list[dict]) -> dict:
    return {"type": "custom:vertical-stack-in-card", "cards": cards,
            "card_mod": {"class": "calm-panel"},
            "grid_options": {"columns": "full", "rows": "auto"}}


def status_chips() -> dict:
    entries = [
        ("sensor.dashboard_readiness_security", "mdi:shield-outline", "{{ 'Security needs attention' if is_state(entity, 'blocked') else 'Security unverified' if not has_value(entity) or is_state(entity, 'unknown') else 'Door ' ~ states('lock.front_door_lock') }}"),
        ("climate.my_ecobee", "mdi:thermometer", "{% set t = state_attr(entity, 'current_temperature') | float(none) %}{{ (t | round(0) | int) ~ '° indoors' if t is not none else 'Temperature unavailable' }}"),
        ("input_select.house_mode", "mdi:home-outline", "{{ states(entity) | replace('_', ' ') | title }} mode"),
    ]
    return {"type": "custom:mushroom-chips-card", "alignment": "start",
            "chips": [{"type": "template", "entity": e, "icon": icon, "content": text,
                       "tap_action": {"action": "none"}} for e, icon, text in entries],
            "grid_options": {"columns": "full"}}


def contextual_cards(root: str) -> list[dict]:
    alarms = summary_card("sensor.dashboard_context",
        "{% if is_state('input_boolean.weekday_alarm_on', 'on') and has_value('input_datetime.weekday_alarm') %}Weekday alarm · {{ states('input_datetime.weekday_alarm')[:5] }}{% elif is_state('input_boolean.weekend_alarm_on', 'on') and has_value('input_datetime.weekend_alarm') %}Weekend alarm · {{ states('input_datetime.weekend_alarm')[:5] }}{% else %}Alarm settings{% endif %}",
        "mdi:alarm", "Weekday {{ states('input_boolean.weekday_alarm_on') }} · Weekend {{ states('input_boolean.weekend_alarm_on') }} · Meeting {{ states('input_boolean.special_meeting') }}", "context")
    travel = summary_card("sensor.dashboard_context", "Travel and readiness", "mdi:airplane-check",
        "{{ 'Review departure preparation' if is_state(entity, 'departure') else 'Return readiness: ' ~ states('sensor.dashboard_return_readiness') ~ ' · Open the evidence checklist' }}", "context")
    unknown = summary_card("sensor.dashboard_context", "Home context is unavailable", "mdi:help-circle-outline",
        "Open household status; all destinations remain available.", "context")
    for card, path, contexts in [(alarms, "owner-suite", ["home", "morning", "evening", "sleep"]),
                                 (travel, "travel", ["away", "return", "departure"]),
                                 (unknown, "house", ["unknown", "unavailable"])]:
        action = {"action": "navigate", "navigation_path": f"{root}/{path}"}
        card.update(tap_action=action)
        card["visibility"] = [{"condition": "state", "entity": "sensor.dashboard_context", "state": contexts}]
    return [alarms, travel, unknown]


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
    templates.pop("calm_readiness", None)  # Readiness rows now share native Tile semantics.
    readiness = [summary_card(f"sensor.dashboard_readiness_{key}", name, "mdi:progress-check",
        "{{ states(entity) | title }} · {{ state_attr(entity, 'reason') or 'Evidence unavailable' }}{% set stamp = as_datetime(state_attr(entity, 'evidence_at'), none) %}{% if stamp is not none %}\nEvidence: {{ (stamp | as_local).strftime('%b %-d, %-I:%M %p %Z') }}{% endif %}", "check")
        for key, name in READINESS]
    for card in readiness:
        card["icon"] = "{{ {'complete': 'mdi:check-circle-outline', 'blocked': 'mdi:alert-circle-outline', 'running': 'mdi:progress-clock', 'scheduled': 'mdi:clock-outline', 'skipped': 'mdi:minus-circle-outline'}.get(states(entity), 'mdi:help-circle-outline') }}"
        card["color"] = "{{ 'red' if is_state(entity, 'blocked') else 'primary' if is_state(entity, 'complete') else 'secondary-text' }}"
    context_card = {"type": "markdown", "text_only": True,
        "entity_id": ["sensor.dashboard_context", "input_select.house_mode", "input_boolean.trip"],
        "card_mod": {"class": "calm-hero"},
        "content": "{% set c = states('sensor.dashboard_context') %}<small>{{ now().strftime('%A') }} · {{ c | replace('_', ' ') | title }}</small>\n# {{ 'A quiet evening.' if c == 'home' and now().hour >= 17 else {'home': 'At home.', 'morning': 'A clear start to the day.', 'evening': 'A quiet evening.', 'sleep': 'Keeping things quiet.', 'departure': 'Ready to leave?', 'away': 'A clear view of home.', 'return': 'Home is getting ready.'}.get(c, 'Home status needs a look.') }}\nYour rooms. The details when you need them.\n\n<small>Home weather · {% set w = 'weather.tomorrow_io_the_brewery_daily' %}{% if has_value(w) %}{{ state_attr(w, 'temperature') if state_attr(w, 'temperature') is not none else '—' }}{{ state_attr(w, 'temperature_unit') or '' }} · {{ states(w) | replace('-', ' ') | title }}{% else %}Unavailable{% endif %}</small>"}
    context_cards = [context_card, status_chips(), *contextual_cards(root)]
    favorites = [tile("light.owner_suite_lamps", "Lamps"), tile("fan.owner_suite", "Ceiling fan"),
                 tile("cover.owner_suite_blinds_ha", "Blinds"), tile("light.owner_suite_bathroom_lights_2", "Bathroom lights"),
                 shortcut("Alarms", f"{root}/owner-suite", "mdi:alarm"),
                 shortcut("Media groups", f"{root}/media-players", "mdi:speaker-multiple")]
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
    for entity, label in [("fan.owner_suite", "Owner-suite ceiling fan"), ("light.owner_suite_lamps", "Owner-suite lamps"),
                          ("cover.owner_suite_blinds_ha", "Owner-suite blinds"), ("media_player.ma_bedroom", "Bedroom audio")]:
        card = tile(entity, label)
        card["visibility"] = [{"condition": "state", "entity": entity, "state": ["unavailable", "unknown"]}]
        exceptions.append(card)
    for index, old in enumerate(exceptions):
        card = summary_card(old["entity"], old.get("name", "{{ state_attr(entity, 'friendly_name') or entity }}"), "mdi:information-outline",
                            "{{ state_attr(entity, 'reason') or (states(entity) | title) }}", "attention")
        card["visibility"] = old["visibility"]
        card["color"] = "{{ 'red' if is_state(entity, 'blocked') else 'secondary-text' }}"
        exceptions[index] = card
    audio = summary_card("media_player.ma_bedroom", "Bedroom audio", "mdi:music-note-outline",
                         "{{ states(entity) | title }}{% if state_attr(entity, 'media_title') %} · {{ state_attr(entity, 'media_title') }}{% endif %}", "player")
    audio.update(features=[{"type": "media-player-playback", "controls": ["media_play_pause"]}], features_position="inline")
    volume = summary_card("media_player.ma_bedroom", "{% set v = state_attr(entity, 'volume_level') | float(none) %}Volume {{ ((v * 100) | round(0) | int) ~ '%' if v is not none else 'unavailable' }}", "", "", "volume")
    volume.update(tap_action={"action": "none"}, icon_tap_action={"action": "none"})
    volume["features"] = [{"type": "media-player-volume-slider"}]
    volume["features_position"] = "inline"
    audio_panel = panel([audio, volume, shortcut("Media controls", f"{root}/media-players", "mdi:arrow-right")])
    whole_house = panel([{"type": "markdown", "text_only": True, "content": "### Whole house"},
        shortcut("Lights", f"{root}/house", "mdi:lightbulb-outline"),
        shortcut("Climate", f"{root}/climate", "mdi:thermometer"),
        shortcut("Media", f"{root}/media-players", "mdi:music-note-outline")])
    attention = section("Needs attention", exceptions, 2)
    attention["visibility"] = [{"condition": "or", "conditions": [card["visibility"][0] for card in exceptions]}]
    home = view("Home", "home", [section("", context_cards),
        section("Your rooms", [two_columns([room_card(r, root) for r in ROOMS[:4]])], 2),
        section("", [audio_panel]), section("", [whole_house]), attention,
        section("Quick controls", [two_columns(favorites)], 2)], root)
    home["max_columns"] = 2
    rooms = view("Rooms", "rooms", [section("Rooms", [{"type": "markdown", "text_only": True, "content": "Room groups first. Individual details when you need them."}]),
        section("Upstairs", [two_columns([room_card(r, root) for r in (ROOMS[0], ROOMS[1], ROOMS[7])])], 2),
        section("Main floor", [two_columns([room_card(r, root) for r in ROOMS[2:6]])], 2),
        section("Other spaces", [two_columns([room_card(r, root) for r in (ROOMS[6], ROOMS[8])])], 2)], root)
    rooms["max_columns"] = 2
    lights = [tile(entity, name, ("light-brightness",)) for name, _, entity, _ in ROOMS
              if not states or entity in states]
    house = view("House", "house", [section("Whole house", [shortcut("Climate details", f"{root}/climate", "mdi:thermostat"), shortcut("Media and groups", f"{root}/media-players", "mdi:speaker-multiple")]),
        section("Room light groups", lights, 2),
        section("Comfort", [tile("climate.my_ecobee", "Thermostat", ("target-temperature",)), shortcut("Climate", f"{root}/climate")], 2),
        section("Household", [shortcut("Cleaning and laundry", f"{root}/cleaning-v2", "mdi:robot-vacuum"), shortcut("Deliveries", f"{root}/deliveries", "mdi:package-variant"), {"type": "todo-list", "entity": "todo.shopping_list"}], 2)], root)
    house["sections"].append(section("House modes", [tile("input_select.house_mode", "House mode"), tile("input_boolean.guest_mode", "Guest mode")], 2))
    travel = view("Travel", "travel", [section("Travel", [tile("input_boolean.trip", "Trip mode"), tile("input_boolean.trip_guest_visit_active", "Guest visit"), {"type": "markdown", "text_only": True, "entity_id": ["sensor.dashboard_return_cycle", "sensor.dashboard_context"], "content": "{% set landing = state_attr('sensor.dashboard_return_cycle', 'landing_at') %}\n{{ 'Flight landing: ' ~ (as_datetime(landing) | as_local).strftime('%a %-I:%M %p %Z') if landing else 'No current return flight is associated.' }}\n\nWater restoration follows the existing trip-end flow. Completion below requires evidence; docking and launch attempts are not proof."}]),
        section("Security and water", [tile("alarm_control_panel.home_alarm", "Alarm"), tile("lock.front_door_lock", "Front door"), tile("cover.garage_door", "Garage"), tile("switch.basement_water_shutoff", "Water supply")], 2),
        section("Arrival readiness", [panel(readiness)], 2),
        section("Pet care", [tile("binary_sensor.main_level_cat_feeder_error", "Main-floor feeder"), tile("binary_sensor.upstairs_cat_feeder_error", "Upstairs feeder"), tile("select.main_level_cat_feeder_mode", "Main-floor schedule"), tile("select.upstairs_cat_feeder_mode", "Upstairs schedule")], 2),
        section("Cameras · open on demand", [tile(e, n) for e, n in [("camera.front_door", "Front entrance"), ("camera.livingroomcamera", "Dining room"), ("camera.tikiroomcamera", "Tiki room")] if not states or e in states], 2)], root)
    old_header = travel["sections"][0]["cards"][0]["cards"]
    travel_modes = old_header[1:3]  # Heading precedes the two original helper controls.
    travel_hero = {"type": "markdown", "text_only": True, "card_mod": {"class": "calm-hero"},
        "content": "<small>Travel · {{ 'Away' if is_state('input_boolean.trip', 'on') else 'Home overview' }}</small>\n# {{ 'Home is getting ready.' if is_state('sensor.dashboard_context', 'return') else 'A clear view of home.' }}\nSecurity, comfort, and the little things."}
    landing = summary_card("sensor.dashboard_return_cycle", "Flight landing", "mdi:airplane-landing",
        "{% set dt = as_datetime(state_attr(entity, 'landing_at'), none) %}{{ (dt | as_local).strftime('%a, %b %-d · %-I:%M %p %Z') if dt is not none else 'No return flight is associated' }}\nWater restoration follows the existing trip-end flow.", "context")
    travel_chips = status_chips()
    travel_chips["chips"][2] = {"type": "template", "entity": "switch.basement_water_shutoff",
        "icon": "mdi:water-outline", "content": "Water reported {{ states(entity) }}", "tap_action": {"action": "none"}}
    travel["sections"][0] = section("", [{"type": "vertical-stack", "grid_options": {"columns": "full"}, "cards": [travel_hero, travel_chips, landing]}], 4)
    overview = []
    for key, label, icon in [("security", "Security", "mdi:shield-outline"), ("pet_care", "Pet care", "mdi:cat"),
                             ("climate", "Temperature", "mdi:thermometer"), ("water", "Water", "mdi:water-outline")]:
        card = summary_card(f"sensor.dashboard_readiness_{key}", label, icon,
            "{{ states(entity) | title }}\n{{ state_attr(entity, 'reason') or 'Evidence unavailable' }}", "overview", vertical=True)
        card["color"] = "{{ 'red' if is_state(entity, 'blocked') else 'primary' if is_state(entity, 'complete') else 'secondary-text' }}"
        overview.append(card)
    travel["sections"].insert(1, section("Home overview", [two_columns(overview)], 2))
    controls = travel["sections"][2]
    controls["cards"] = [controls["cards"][0], two_columns(controls["cards"][1:])]
    cameras = travel["sections"][-1]
    cameras["cards"] = [cameras["cards"][0], two_columns([
        summary_card(c["entity"], c.get("name", "Camera"), "mdi:video-outline", "Open on demand", "camera", vertical=True)
        for c in cameras["cards"][1:]])]
    travel["sections"].append(section("Travel modes", travel_modes, 2))
    travel["max_columns"] = 2
    # Supply-altering controls open native details; context never operates them.
    for card in controls["cards"][1]["cards"]:
        if card.get("entity") in {"lock.front_door_lock", "cover.garage_door", "switch.basement_water_shutoff"}:
            card["icon_tap_action"] = {"action": "more-info"}
            card["hold_action"] = {"action": "more-info"}
    originals = result["views"]
    more_links = [shortcut(v.get("title", "Details"), f"{root}/{v.get('path', i)}", v.get("icon", "mdi:view-dashboard-outline"))
                  for i, v in enumerate(originals) if i and v.get("path") not in PRIMARY]
    more = view("More", "more", [section("More", [shortcut("Security dashboard", "/security", "mdi:shield-home-outline"), shortcut("Flight Deck", "/flight-deck", "mdi:airplane-clock")]), section("Specialist views", more_links, 2)], root)
    more["sections"].append(section("Administration", [shortcut("Settings", "/config", "mdi:cog-outline"),
        shortcut("Profile and appearance", "/profile", "mdi:account-circle-outline"),
        shortcut("History", "/history", "mdi:history")], 2))
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
    for primary in [home, *additions.values()]:
        apply_typography(primary)
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
