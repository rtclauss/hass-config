"""#1223: wake/snooze gate on canonical presence; presence faults are surfaced;
AppDaemon app_dir is nested where AppDaemon 4.5 reads it."""

from __future__ import annotations

from pathlib import Path

import yaml

from privacy_ids import PRESENCE_SENSOR, PRESENCE_TRACKER

ROOT = Path(__file__).resolve().parents[1]
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"
APPDAEMON_CONFIG = ROOT / "appdaemon" / "appdaemon.yaml"


class _TagTolerantLoader(yaml.SafeLoader):
    pass


_TagTolerantLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: loader.construct_scalar(node)
)


def _load(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_TagTolerantLoader)


def _automation(path: Path, automation_id: str) -> dict:
    for automation in _load(path)["automation"]:
        if automation.get("id") == automation_id:
            return automation
    raise AssertionError(f"automation {automation_id!r} not found in {path.name}")


def _flatten_conditions(conditions):
    if isinstance(conditions, dict):
        conditions = [conditions]
    for condition in conditions:
        yield condition
        nested = condition.get("conditions")
        if nested:
            yield from _flatten_conditions(nested)


def _state_conditions(automation: dict) -> dict:
    return {
        c["entity_id"]: c["state"]
        for c in _flatten_conditions(automation["condition"])
        if c.get("condition") == "state"
    }


def test_alarm_wake_up_gates_on_canonical_presence() -> None:
    conditions = _state_conditions(_automation(WORKDAY_PATH, "alarm_wake_up"))

    assert conditions[PRESENCE_SENSOR] == "on"
    assert PRESENCE_TRACKER not in conditions
    # Existing protections are preserved.
    assert conditions["binary_sensor.planned_vacation_calendar"] == "off"
    assert conditions["input_boolean.master_bed_occupancy"] == "on"


def test_alarm_snooze_gates_on_canonical_presence() -> None:
    conditions = _state_conditions(_automation(WORKDAY_PATH, "alarm_snooze"))

    assert conditions[PRESENCE_SENSOR] == "on"
    assert PRESENCE_TRACKER not in conditions
    assert conditions["input_boolean.wakeup_alarm_firing"] == "on"
    assert conditions["input_boolean.master_bed_occupancy"] == "on"


def test_meeting_precedence_unchanged() -> None:
    text = WORKDAY_PATH.read_text(encoding="utf-8")
    block = text[text.index("  - id: alarm_wake_up"):text.index("  - id: workday_owner_suite_wake_transition")]

    assert "weekday alarm is before meeting reminder" in block
    assert "entity_id: input_boolean.special_meeting\n                    state: \"off\"" in block
    # Meeting branch still clears the flag only when it actually fires.
    assert "action: input_boolean.turn_off\n                target:\n                  entity_id: input_boolean.special_meeting" in block


def test_gps_zone_consumers_keep_fused_tracker() -> None:
    arrive = _automation(WORKDAY_PATH, "arrive_at_work")
    assert arrive["trigger"][0]["entity_id"] == PRESENCE_TRACKER


def _presence_problem_sensor() -> dict:
    for block in _load(ZONE_PATH)["template"]:
        for sensor in block.get("binary_sensor", []):
            if sensor.get("unique_id") == "presence_tracker_problem":
                return sensor
    raise AssertionError("presence_tracker_problem template binary_sensor missing")


def test_presence_problem_sensor_flags_contradiction_and_missing_data() -> None:
    sensor = _presence_problem_sensor()
    state = sensor["state"]
    status_entity = PRESENCE_TRACKER.replace("device_tracker.", "sensor.") + "_tracker_status"

    assert sensor["device_class"] == "problem"
    assert sensor["delay_on"] == {"minutes": 10}
    assert PRESENCE_SENSOR in state
    assert PRESENCE_TRACKER in state
    assert status_entity in state
    assert "bayes == 'on' and tracker != 'home'" in state
    assert "['unknown', 'unavailable']" in state
    assert "config_error" in state


def test_presence_problem_alert_notifies_and_clears() -> None:
    automation = _automation(ZONE_PATH, "presence_tracker_problem_alert")
    trigger_ids = {t["id"] for t in automation["triggers"]}
    text = yaml.safe_dump(automation)

    assert trigger_ids == {"problem", "recovered"}
    assert "persistent_notification.create" in text
    assert "persistent_notification.dismiss" in text
    assert "notify.all" in text


def test_appdaemon_app_dir_nested_under_appdaemon_section() -> None:
    config = _load(APPDAEMON_CONFIG)

    assert "app_dir" not in config, "top-level app_dir is ignored by AppDaemon 4.5"
    assert config["appdaemon"]["app_dir"] == "/config/apps"
