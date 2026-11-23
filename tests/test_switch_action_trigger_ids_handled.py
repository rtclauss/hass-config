"""Switch action automations must handle every trigger ID they listen for.

A trigger ID with no matching ``condition: trigger`` branch fires the
automation, records a trace, and does nothing, which reads like a broken
switch gesture. Either map the gesture or drop the trigger.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"

# Gestures that still trigger without a branch, pending an owner decision to
# map or drop them. Remove an entry once it is resolved; the test fails if an
# entry goes stale or a new unhandled gesture appears.
KNOWN_UNHANDLED = {
    "kitchen_overhead_switch_actions": {"up-double", "down-double"},
    "laundry_switch_actions": {"down-double"},
}


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant tags such as !secret/!include."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, _suffix, node: loader.construct_scalar(node)
    if isinstance(node, yaml.ScalarNode)
    else None,
)


def _handled_ids(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        if node.get("condition") == "trigger":
            ids = node.get("id")
            found |= set(ids if isinstance(ids, list) else [ids])
        for value in node.values():
            found |= _handled_ids(value)
    elif isinstance(node, list):
        for item in node:
            found |= _handled_ids(item)
    return found


def _switch_action_automations() -> list[dict]:
    package = yaml.load(ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8"), Loader=_Loader)
    return [
        a for a in package["automation"]
        if isinstance(a, dict) and str(a.get("id", "")).endswith("_switch_actions")
    ]


@pytest.mark.parametrize("automation", _switch_action_automations(), ids=lambda a: a["id"])
def test_every_trigger_id_has_a_branch(automation: dict) -> None:
    triggers = automation.get("trigger") or automation.get("triggers") or []
    trigger_ids = {t["id"] for t in triggers if isinstance(t, dict) and t.get("id")}
    unhandled = trigger_ids - _handled_ids(automation.get("action") or automation.get("actions"))
    expected = KNOWN_UNHANDLED.get(automation["id"], set())
    assert unhandled == expected, (
        f"{automation['id']} unhandled gestures {sorted(unhandled)}; "
        f"KNOWN_UNHANDLED lists {sorted(expected)}"
    )
