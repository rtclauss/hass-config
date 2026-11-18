from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MOUSE_TRAP_PATH = ROOT / "packages" / "mouse_trap.yaml"
RESET_ACTION = "MICE_CAUGHT_RESET"


def _automations() -> dict[str, dict]:
    package = yaml.safe_load(MOUSE_TRAP_PATH.read_text(encoding="utf-8"))
    return {automation["id"]: automation for automation in package["automation"]}


def test_catch_notification_offers_reset_action() -> None:
    automation = _automations()["mouse_bucket_notify_and_count_on_catch"]
    notify = next(
        step for step in automation["action"] if step.get("action") == "notify.notify"
    )
    actions = notify["data"]["data"]["actions"]

    assert {"action": RESET_ACTION, "title": "Reset to zero", "destructive": True} in actions
    assert notify["data"]["data"]["tag"] == "mice-caught"


def test_reset_action_resets_counter() -> None:
    automation = _automations()["mouse_bucket_reset_counter_from_notification"]

    assert automation["trigger"] == [
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": RESET_ACTION},
        }
    ]
    assert automation["action"][0] == {
        "action": "counter.reset",
        "target": {"entity_id": "counter.mice_caught"},
    }
