"""Guest-mode regressions found during the Nov 2026 guest stay review."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]


class ConfigLoader(yaml.SafeLoader):
    """Preserve opaque HA tags without resolving secrets or includes."""


ConfigLoader.add_constructor(None, lambda loader, node: loader.construct_scalar(node))


def _config(path: str) -> dict:
    return yaml.load((ROOT / path).read_text(), Loader=ConfigLoader)


def _automation(path: str, automation_id: str) -> dict:
    return next(item for item in _config(path)["automation"] if item["id"] == automation_id)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _guest_gate(conditions: list[dict]) -> bool:
    return any(
        c.get("condition") == "state"
        and "input_boolean.guest_mode" in (
            [c["entity_id"]] if isinstance(c.get("entity_id"), str) else c.get("entity_id", [])
        )
        and c.get("state") == "off"
        for c in conditions
    )


# --- guest Wi-Fi presence -------------------------------------------------


def test_guest_on_wifi_reads_current_unifi_wlan_sensor() -> None:
    sensor = next(
        item
        for block in _config("packages/guest.yaml")["template"]
        for item in block.get("binary_sensor", [])
        if item["unique_id"] == "guest_on_wifi"
    )
    # UniFi re-keyed the guest WLAN on 2026-11-12; the old sensor.barley_guest
    # is an orphan that stays unavailable.
    assert "sensor.barley_guest_clients" in sensor["state"]
    assert "states('sensor.barley_guest')" not in sensor["state"]


def test_guest_mode_auto_off_works_when_guest_mode_was_enabled_by_hand() -> None:
    automation = _automation("packages/guest.yaml", "turn_off_guest_mode_when_guest_wifi_inactive")
    guest_triggers = [t for t in automation["trigger"] if t.get("entity_id") == "input_boolean.guest_mode"]
    assert guest_triggers and guest_triggers[0]["to"] == "on"
    assert guest_triggers[0]["for"] == {"hours": 16}
    assert any(t["trigger"] == "time_pattern" for t in automation["trigger"])

    conditions = {c["entity_id"]: c for c in automation["condition"]}
    assert conditions["input_boolean.guest_mode"]["state"] == "on"
    assert conditions["input_boolean.guest_mode"]["for"] == {"hours": 16}
    assert conditions["binary_sensor.guest_on_wifi"]["state"] == "off"
    assert conditions["binary_sensor.guest_on_wifi"]["for"] == {"hours": 16}


def test_guest_mode_auto_on_does_not_prompt_when_already_on() -> None:
    automation = _automation("packages/guest.yaml", "turn_on_guest_mode_when_guest_wifi_active")
    assert {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "off"} in automation["condition"]


# --- media/climate policy on any guest-mode change ------------------------


def test_any_guest_mode_change_reapplies_media_and_climate() -> None:
    automation = _automation("packages/guest.yaml", "apply_guest_mode_policy_on_change")
    transitions = {(t["from"], t["to"]) for t in automation["trigger"]}
    assert transitions == {("off", "on"), ("on", "off")}
    assert all(t["entity_id"] == "input_boolean.guest_mode" for t in automation["trigger"])

    calls = [n for n in _walk(automation["action"]) if n.get("action") == "script.house_transition"]
    assert len(calls) == 1
    data = calls[0]["data"]
    assert data["apply_media"] is True
    assert data["apply_climate"] is True
    assert data["apply_lights"] is False
    assert data["apply_security"] is False


@pytest.mark.parametrize(
    "automation_id",
    ["turn_on_guest_mode_when_guest_wifi_active", "turn_off_guest_mode_when_guest_wifi_inactive"],
)
def test_wifi_automations_leave_policy_to_the_change_automation(automation_id: str) -> None:
    automation = _automation("packages/guest.yaml", automation_id)
    assert not [n for n in _walk(automation["action"]) if n.get("action") == "script.house_transition"]


# --- hallway / stairway vacancy-off during guest mode ---------------------


@pytest.mark.parametrize(
    ("automation_id", "on_branches", "off_branches"),
    [
        ("hallway_light_toggle_at_night", (0, 3), (1, 2, 4, 5)),
        ("toggle_hallway_day", (0, 2), (1, 3)),
    ],
)
def test_guest_mode_suppresses_hallway_turn_on_but_not_vacancy_off(
    automation_id: str, on_branches: tuple[int, ...], off_branches: tuple[int, ...],
) -> None:
    automation = _automation("packages/light.yaml", automation_id)
    assert not _guest_gate(automation["condition"])
    branches = automation["action"][0]["choose"]
    for index in on_branches:
        assert _guest_gate(branches[index]["conditions"]), index
        assert any(n.get("action") == "script.hallway_lights_turn_on" for n in _walk(branches[index]["sequence"]))
    for index in off_branches:
        assert not _guest_gate(branches[index]["conditions"]), index
        assert any(n.get("action") == "light.turn_off" for n in _walk(branches[index]["sequence"]))


# --- catnip grow light guest window ---------------------------------------


def _should_be_on(hour: int, guest_mode: str, trip_visit: str = "off") -> bool:
    reconcile = _automation("packages/plants.yaml", "catnip_grow_light_reconcile")
    template = next(
        step["variables"]["should_be_on"] for step in reconcile["action"] if "variables" in step
    )
    states = {"input_boolean.guest_mode": guest_mode, "input_boolean.trip_guest_visit_active": trip_visit}
    env = Environment()
    env.globals["now"] = lambda: datetime(2026, 11, 14, hour, 30)
    env.globals["is_state"] = lambda entity_id, value: states[entity_id] == value
    rendered = env.from_string(template).render().strip()
    # HA only coerces Python literals; anything else (e.g. "false") stays a
    # truthy string, so the template must render exactly True or False.
    assert rendered in {"True", "False"}, rendered
    return rendered == "True"


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, False), (6, True), (10, True), (11, True), (21, True), (22, True), (23, True)],
)
def test_catnip_normal_schedule_is_six_to_midnight(hour: int, expected: bool) -> None:
    assert _should_be_on(hour, "off") is expected


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, False), (6, False), (10, False), (11, True), (15, True), (21, True), (22, False), (23, False)],
)
def test_catnip_guest_window_is_eleven_to_ten(hour: int, expected: bool) -> None:
    assert _should_be_on(hour, "on") is expected


def test_catnip_trip_guest_visit_still_keeps_light_off() -> None:
    assert _should_be_on(15, "on", trip_visit="on") is False
    assert _should_be_on(15, "off", trip_visit="on") is False


def test_catnip_reconcile_fires_at_guest_window_boundaries() -> None:
    reconcile = _automation("packages/plants.yaml", "catnip_grow_light_reconcile")
    times = [t for t in reconcile["trigger"] if t["trigger"] == "time"]
    assert times and set(times[0]["at"]) == {"11:00:00", "22:00:00"}


def test_room_intent_places_grow_light_in_unfinished_basement() -> None:
    intent = yaml.safe_load((ROOT / "docs/room_intent.yaml").read_text())
    room = intent["rooms"]["unfinished_basement"]
    prefs = " ".join(room["automation_guidance"]["owner_preferences"])
    assert "switch.basement_grow_light" in prefs
    assert "22:00 to 11:00" in prefs
