from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
STAIRWAY = "light.hall_stairway_bulbs"


class ConfigLoader(yaml.SafeLoader):
    """Preserve opaque HA tags without resolving secrets or includes."""


ConfigLoader.add_constructor(None, lambda loader, node: loader.construct_scalar(node))


def _config(path: str) -> dict:
    return yaml.load((ROOT / path).read_text(), Loader=ConfigLoader)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _automation(path: str, automation_id: str) -> dict:
    return next(item for item in _config(path)["automation"] if item["id"] == automation_id)


def _targets(action: dict) -> list[str]:
    targets = action.get("target", {}).get("entity_id", action.get("data", {}).get("entity_id", []))
    return [targets] if isinstance(targets, str) else targets


@pytest.mark.parametrize(
    ("automation_id", "branch_index"),
    [("hallway_light_toggle_at_night", i) for i in (1, 2, 4, 5)]
    + [("toggle_hallway_day", i) for i in (1, 3)],
)
def test_every_hallway_vacancy_branch_turns_off_actual_stairway_bulbs(
    automation_id: str, branch_index: int,
) -> None:
    automation = _automation("packages/light.yaml", automation_id)
    branch = automation["action"][0]["choose"][branch_index]
    actions = [node for node in _walk(branch["sequence"]) if node.get("action") == "light.turn_off"]
    assert len(actions) == 1
    assert STAIRWAY in _targets(actions[0])
    assert "light.hall_stairway" not in _targets(actions[0])
    assert actions[0]["data"]["transition"] == 5


@pytest.mark.parametrize("automation_id", ["hallway_light_toggle_at_night", "toggle_hallway_day"])
def test_motion_on_uses_both_profiles_only_after_existing_bed_guard(automation_id: str) -> None:
    automation = _automation("packages/light.yaml", automation_id)
    on_branches = [
        branch for branch in automation["action"][0]["choose"]
        if branch["conditions"][0]["id"].endswith("motion-sensed")
    ]
    assert len(on_branches) == 2
    for branch in on_branches:
        assert branch["conditions"][1] == {
            "condition": "state", "entity_id": "binary_sensor.bayesian_bed_occupancy", "state": "off",
        }
        assert branch["sequence"][0] == {
            "action": "script.hallway_lights_turn_on", "data": {"transition": 1},
        }


@pytest.mark.parametrize("transition", [None, 0, 1, 5])
def test_shared_turn_on_keeps_profiles_separate_and_preserves_transition(transition: int | None) -> None:
    script = _config("scripts.yaml")["hallway_lights_turn_on"]
    calls = script["sequence"]
    assert [(call["data"]["adaptive_switch"], call["data"]["lights"]) for call in calls] == [
        ("switch.adaptive_lighting_hallway", ["light.hall_all"]),
        ("switch.adaptive_lighting_stairway", [STAIRWAY]),
    ]
    for call in calls:
        assert call["action"] == "script.adaptive_light_turn_on"
        context = {} if transition is None else {"transition": transition}
        rendered = Environment().from_string(call["data"]["transition"]).render(context)
        assert int(rendered) == (1 if transition is None else transition)


@pytest.mark.parametrize("path", ["packages/light.yaml", "packages/zone.yaml", "packages/zigbee_zwave.yaml"])
def test_all_explicit_whole_hall_commands_and_scenes_include_stairway(path: str) -> None:
    config = _config(path)
    for node in _walk(config):
        if "light.hall_all" in _targets(node):
            assert STAIRWAY in _targets(node), node
        if "entities" in node and isinstance(node["entities"], dict) and "light.hall_all" in node["entities"]:
            assert node["entities"][STAIRWAY] == node["entities"]["light.hall_all"]
    for node in _walk(config):
        assert "light.hall_stairway" not in node
        assert "light.hall_stairway" not in node.values()
        assert "light.hall_stairway" not in _targets(node)


@pytest.mark.parametrize(
    ("path", "scene_id", "state"),
    [
        ("packages/light.yaml", "cloudy_arrive_home", "on"),
        ("packages/light.yaml", "night_arrive_home", "on"),
        ("packages/zone.yaml", "arrive_home_multi_day", "on"),
        ("packages/zone.yaml", "goodnight", "off"),
        ("packages/zone.yaml", "leave_home", "off"),
    ],
)
def test_arrival_and_shutdown_scenes_control_stairway_group(path: str, scene_id: str, state: str) -> None:
    scene = next(item for item in _config(path)["scene"] if item["id"] == scene_id)
    assert scene["entities"][STAIRWAY]["state"] == state


def test_basement_vacancy_uses_light_domain_for_stairway_shutdown() -> None:
    automation = _automation("packages/light.yaml", "turn_off_basement_light_when_dark_in_room")
    assert automation["action"][0] == {"action": "light.turn_off", "target": {"entity_id": STAIRWAY}}


def test_hallway_double_tap_controls_both_groups() -> None:
    automation = _automation("packages/zigbee_zwave.yaml", "hall_transition_switch_actions")
    on, off = automation["action"][0]["choose"]
    assert on["sequence"][0]["action"] == "script.hallway_lights_turn_on"
    assert set(_targets(off["sequence"][0])) == {"light.hall_all", STAIRWAY}


@pytest.mark.parametrize("path", ["ui-guest.yaml", "lovelace/tiles/tiles_other.yaml"])
def test_direct_stairway_controls_use_bulb_group(path: str) -> None:
    text = (ROOT / path).read_text()
    assert f"entity: {STAIRWAY}\n" in text
    assert "entity: light.hall_stairway\n" not in text


def test_whole_house_shutdown_includes_bulbs_even_when_wall_switch_reports_off() -> None:
    script = _config("packages/light.yaml")["script"]["lights_off_except"]
    bulbs = [f"light.hall_stairway_bulb_{index}" for index in range(1, 7)]
    lights = [SimpleNamespace(entity_id=entity, state="on") for entity in bulbs]
    lights += [SimpleNamespace(entity_id="light.hall_stairway", state="off")]
    lights += [SimpleNamespace(entity_id="light.outside_front_hue", state="on")]
    template = Environment().from_string(script["variables"]["all_other_lights"])
    result = template.render(states=SimpleNamespace(light=lights), protected_lights=["light.outside_front_hue"])
    assert {entity.strip() for entity in result.split(",")} == set(bulbs)
