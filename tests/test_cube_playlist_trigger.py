"""Cube playlist selections must not replay sensor initialization as a flip."""

from pathlib import Path

import jinja2
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SIDES = tuple(str(side) for side in range(6))


@pytest.fixture(scope="module")
def selection() -> dict:
    # Read the generated package, just as HA does. conftest renders synthetic
    # private values before collection; !secret scalars can stay as plain strings.
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
    package = yaml.load((ROOT / "packages/media_player.yaml").read_text(), Loader=Loader)
    return next(item for item in package["automation"] if item["id"] == "bedroom_music_select_playlist")


def test_selection_uses_native_state_filters(selection: dict) -> None:
    trigger, = selection["trigger"]
    assert trigger["trigger"] == "state"
    assert trigger["entity_id"] == "sensor.owner_suite_cube_action_to_side"
    assert set(trigger["from"]) == {"", "None", *SIDES}
    assert set(trigger["to"]) == set(SIDES)
    assert "not_from" not in trigger
    assert "not_to" not in trigger
    assert "attribute" not in trigger


@pytest.mark.parametrize("old", [None, "unknown", "unavailable", "invalid"])
@pytest.mark.parametrize("new", ["", "None", *SIDES])
def test_startup_and_recovery_never_select_a_playlist(selection: dict, old, new: str) -> None:
    trigger, = selection["trigger"]
    # Native `from` and `to` lists are ANDed. A missing old State has value None.
    assert not (old in trigger["from"] and new in trigger["to"])


@pytest.mark.parametrize("old", ["", "None", *SIDES])
@pytest.mark.parametrize("new", [None, "", "None", "unknown", "unavailable", "-1", "6", "1.0", "invalid"])
def test_idle_resets_and_invalid_sides_never_select_a_playlist(selection: dict, old: str, new) -> None:
    trigger, = selection["trigger"]
    assert not (old in trigger["from"] and new in trigger["to"])


@pytest.mark.parametrize(
    ("old", "side"),
    [(old, side) for old in ["", "None", *SIDES] for side in SIDES if old != side],
)
def test_real_flips_preserve_notifications_and_script_mapping(selection: dict, old: str, side: str) -> None:
    trigger, = selection["trigger"]
    assert old in trigger["from"] and side in trigger["to"]
    notify, play = selection["action"]
    assert notify["action"] == "notify.all"
    assert play["action"] == "script.turn_on"
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    variables = {"trigger": {"to_state": {"state": side}}}
    expected = f"script.bedroom_playlist_{side}"
    assert env.from_string(notify["data"]["message"]).render(variables) == expected
    assert env.from_string(play["target"]["entity_id"]).render(variables) == expected


def test_every_allowed_side_has_a_script() -> None:
    package = (ROOT / "packages/media_player.yaml").read_text()
    for side in SIDES:
        assert f"\n  bedroom_playlist_{side}:\n" in package
