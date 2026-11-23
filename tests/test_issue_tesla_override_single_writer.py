"""The max-range override must not race the departure planner at home.

Turning input_boolean.long_range_travel off used to start two automations that
both wrote the charge limit: the planner set the alarm-tier target (85%) and
set_charging_rate overwrote it a second later with a hardcoded 80%.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from privacy_ids import VEHICLE_ENTITY_SLUG, VEHICLE_TRACKER


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"
CHARGE_LIMIT = f"number.{VEHICLE_ENTITY_SLUG}_charge_limit"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _automation(automation_id: str) -> dict:
    data = yaml.load(CAR_PATH.read_text(encoding="utf-8"), Loader=_Loader)
    for automation in data["automation"]:
        if automation.get("id") == automation_id:
            return automation
    raise AssertionError(f"Could not find automation {automation_id!r}")


def _branches() -> list[dict]:
    (choose_step,) = _automation("set_charging_rate")["action"]
    return choose_step["choose"]


def _trigger_ids(branch: dict) -> set[str]:
    ids = branch["conditions"][0]["id"]
    return set(ids if isinstance(ids, list) else [ids])


def _writes_charge_limit(branch: dict) -> bool:
    return any(
        step.get("action") == "number.set_value"
        and step.get("target", {}).get("entity_id") == CHARGE_LIMIT
        for step in branch["sequence"]
    )


def test_notification_actions_only_toggle_the_override() -> None:
    for branch in _branches():
        if _trigger_ids(branch) & {"notify_max_range", "notify_normal_range"}:
            assert not _writes_charge_limit(branch)


def test_notification_toggle_does_not_drop_the_state_run() -> None:
    # A notification action toggles the boolean mid-run; under the default
    # `single` mode the resulting state-triggered run would be discarded.
    assert _automation("set_charging_rate").get("mode") == "queued"


def test_override_writes_charge_limit_only_when_car_is_away() -> None:
    writers = [branch for branch in _branches() if _writes_charge_limit(branch)]

    assert len(writers) == 1
    (writer,) = writers
    assert _trigger_ids(writer) == {"max_range", "normal_range"}
    (guard,) = [c for c in writer["conditions"] if c.get("condition") == "not"]
    assert guard["conditions"] == [
        {"condition": "state", "entity_id": VEHICLE_TRACKER, "state": "home"}
    ]


def test_planner_still_reacts_to_override_at_home() -> None:
    planner = _automation("tesla_departure_planner_apply")
    planner_inputs = [
        trigger for trigger in planner["trigger"] if trigger.get("id") == "planner_input"
    ]

    assert any(
        "input_boolean.long_range_travel" in trigger["entity_id"] for trigger in planner_inputs
    )
    assert re.search(
        r"manual_override = is_state\('input_boolean\.long_range_travel', 'on'\)",
        CAR_PATH.read_text(encoding="utf-8"),
    )
