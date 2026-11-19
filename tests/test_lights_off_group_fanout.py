"""Exercise the actual target template against overlapping HA group inventories."""
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def targets(states, members, groups, protected=(), excluded=None):
    script = yaml.safe_load((ROOT / "packages/light.yaml").read_text())["script"]["lights_off_except"]
    template = Environment(undefined=StrictUndefined).from_string(script["variables"]["all_other_lights"])
    context = dict(
        states=SimpleNamespace(light=[SimpleNamespace(entity_id=k, state=v) for k, v in states.items()]),
        state_attr=lambda entity, attr: members.get(entity),
        integration_entities=lambda integration: groups if integration == "group" else [],
        protected_lights=protected,
    )
    if excluded is not None:
        context["protected_lights"] = NativeEnvironment().from_string(
            script["variables"]["protected_lights"]
        ).render(**context, exclude_lights=excluded)
    result = template.render(**context).strip()
    return [item.strip() for item in result.split(",") if item.strip()]


def test_overlapping_native_groups_do_not_resend_to_selected_members():
    members = {"light.room": ["light.a", "light.b"], "light.table": ["light.a"]}
    states = dict.fromkeys([*members, "light.a", "light.b"], "on")
    assert targets(states, members, list(members)) == ["light.a", "light.b"]


def test_nested_groups_keep_exact_leaf_coverage():
    members = {"light.room": ["light.table", "light.b"], "light.table": ["light.a"]}
    states = dict.fromkeys([*members, "light.a", "light.b"], "on")
    assert targets(states, members, list(members)) == ["light.a", "light.b"]


@pytest.mark.parametrize("member_state", ["off", "unknown", "unavailable", None])
def test_incomplete_group_coverage_retains_original_group_command(member_state):
    states = {"light.room": "on", "light.a": "on"}
    if member_state is not None:
        states["light.b"] = member_state
    assert targets(states, {"light.room": ["light.a", "light.b"]}, ["light.room"]) == ["light.room", "light.a"]


def test_protected_member_and_its_group_remain_excluded():
    states = dict.fromkeys(["light.room", "light.a", "light.b"], "on")
    assert targets(states, {"light.room": ["light.a", "light.b"]}, ["light.room"],
                   excluded=["light.a"]) == []


def test_non_native_groups_and_individual_lights_are_not_rewritten():
    states = dict.fromkeys(["light.mqtt_group", "light.a"], "on")
    assert targets(states, {"light.mqtt_group": ["light.a"]}, []) == list(states)


@pytest.mark.parametrize("members", [None, [], "light.a"])
def test_missing_or_invalid_native_membership_is_not_pruned(members):
    states = {"light.room": "on", "light.a": "on"}
    assert targets(states, {"light.room": members}, ["light.room"]) == list(states)


def test_all_off_still_produces_no_service_targets():
    assert targets({"light.room": "off", "light.a": "off"}, {"light.room": ["light.a"]}, ["light.room"]) == []
