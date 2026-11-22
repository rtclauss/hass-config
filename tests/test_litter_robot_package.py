"""Litter-Robot bag and litter reminders: one push per task, silent clear on fix."""

from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "litter_robot.yaml"
DRAWER_CODES = ["df1", "df2", "dfs"]


def _config():
    return yaml.safe_load(PACKAGE.read_text())


def _automation(automation_id):
    return next(a for a in _config()["automation"] if a["id"] == automation_id)


def _branches(automation):
    choose = automation["action"][0]["choose"]
    clear, push = choose
    return clear, push


@pytest.mark.parametrize(
    "automation_id,latch,tag,need_ids,fix_id",
    [
        (
            "litter_robot_replace_bag_reminder",
            "input_boolean.litter_robot_bag_reminder_sent",
            "litter_robot_replace_bag",
            ["drawer_full", "daily_recheck"],
            "drawer_emptied",
        ),
        (
            "litter_robot_add_litter_reminder",
            "input_boolean.litter_robot_litter_reminder_sent",
            "litter_robot_add_litter",
            ["litter_low", "daily_recheck"],
            "litter_refilled",
        ),
    ],
)
def test_push_once_then_clear_the_same_notification(automation_id, latch, tag, need_ids, fix_id):
    automation = _automation(automation_id)
    assert automation["mode"] == "queued"
    clear, push = _branches(automation)

    # The push needs the latch off, and latches only after the send succeeds.
    assert {"condition": "trigger", "id": need_ids} in push["conditions"]
    assert {"condition": "state", "entity_id": latch, "state": "off"} in push["conditions"]
    notify, set_latch = push["sequence"]
    assert notify["action"] == "notify.all"
    assert notify["data"]["data"]["tag"] == tag
    assert set_latch == {"action": "input_boolean.turn_on", "target": {"entity_id": latch}}

    # The fix clears the latch and removes the phone notification silently.
    assert {"condition": "trigger", "id": fix_id} in clear["conditions"]
    assert {"condition": "state", "entity_id": latch, "state": "on"} in clear["conditions"]
    unlatch, dismiss = clear["sequence"]
    assert unlatch == {"action": "input_boolean.turn_off", "target": {"entity_id": latch}}
    assert dismiss["action"] == "notify.all"
    assert dismiss["data"] == {"message": "clear_notification", "data": {"tag": tag}}


def test_latches_restore_across_restarts():
    for helper in _config()["input_boolean"].values():
        assert "initial" not in helper


def test_thresholds_are_helpers_not_literals():
    text = PACKAGE.read_text()
    assert "above: input_number.litter_robot_drawer_full_threshold" in text
    assert "below: input_number.litter_robot_litter_low_threshold" in text
    numbers = _config()["input_number"]
    assert numbers["litter_robot_drawer_full_threshold"]["initial"] == 80
    assert numbers["litter_robot_litter_low_threshold"]["initial"] == 70


def test_drawer_full_status_codes_trigger_and_block_the_clear():
    automation = _automation("litter_robot_replace_bag_reminder")
    status_trigger = next(
        t for t in automation["trigger"] if t.get("entity_id") == "sensor.main_level_status_code"
    )
    assert status_trigger["id"] == "drawer_full"
    assert status_trigger["to"] == DRAWER_CODES
    clear, _ = _branches(automation)
    blocked = next(c for c in clear["conditions"] if c["condition"] == "not")
    assert blocked["conditions"][0]["state"] == DRAWER_CODES


@pytest.mark.parametrize(
    "code,level,expected",
    [
        ("dfs", "100", "is full and it will stop cycling"),
        ("df1", "90", "nearly full (2 cycles left)"),
        ("df2", "95", "nearly full (1 cycle left)"),
        ("rdy", "85", "is 85% full"),
    ],
)
def test_bag_message_describes_how_urgent_it_is(code, level, expected):
    _, push = _branches(_automation("litter_robot_replace_bag_reminder"))
    template = push["sequence"][0]["data"]["message"]
    values = {
        "sensor.main_level_status_code": code,
        "sensor.main_level_waste_drawer": level,
    }
    message = " ".join(
        jinja2.Environment(undefined=jinja2.StrictUndefined)
        .from_string(template)
        .render(states=values.__getitem__)
        .split()
    )
    assert expected in message
    assert message.endswith("Empty it and put in a new bag.")


def test_litter_message_rounds_the_level():
    _, push = _branches(_automation("litter_robot_add_litter_reminder"))
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["float"] = lambda value, default=0: float(value)
    message = env.from_string(push["sequence"][0]["data"]["message"]).render(
        states=lambda entity_id: "64.6"
    )
    assert "down to 65%" in message
