"""Static checks for the coffee station YAML: helpers, the AppDaemon-independent
safety layer, the dashboard, and the apps.yaml template entry."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUG = "switch.coffee_maker"
REMOTE = "sensor.coffee_station_remote_action"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _load(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), _Loader)


def _package() -> dict:
    return _load(ROOT / "packages" / "coffee.yaml")


def _automation(automation_id: str) -> dict:
    return next(a for a in _package()["automation"] if a["id"] == automation_id)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _app_block() -> dict:
    text = (ROOT / "private_templates" / "appdaemon_apps.yaml.tmpl").read_text(encoding="utf-8")
    block = "coffee_station:" + text.split("\ncoffee_station:", 1)[1]
    return yaml.safe_load(block.replace("@@PRIVATE:presence_person_slug@@", "example"))["coffee_station"]


def test_yaml_safety_layer_never_turns_the_coffee_maker_on():
    pkg = _package()
    for node in _walk([pkg["automation"], pkg["script"]]):
        action = node.get("action")
        assert action not in ("switch.turn_on", "switch.toggle", "homeassistant.turn_on", "homeassistant.toggle")


def test_unplug_alert_is_critical_on_ios_and_android_and_local():
    seq = _package()["script"]["coffee_unplug_alert"]["sequence"]
    assert seq[0]["action"] == "persistent_notification.create"
    data = seq[1]["data"]["data"]
    assert data["push"]["sound"]["critical"] == 1
    assert data["channel"] == "alarm_stream" and data["priority"] == "high" and data["ttl"] == 0


def test_emergency_stop_covers_remote_dashboard_and_notification_and_confirms():
    auto = _automation("coffee_emergency_stop")
    triggers = auto["trigger"]
    remote = next(t for t in triggers if t.get("entity_id") == REMOTE)
    assert set(remote["to"]) == {"off", "brightness_move_down"}
    # Raw MQTT triggers fire on every press, even if the action sensor does not change.
    mqtt = [t for t in triggers if t["trigger"] == "mqtt"]
    assert {t["payload"] for t in mqtt} == {"off", "brightness_move_down"}
    assert all(t["topic"] == "zigbee2mqtt/coffee_station_remote" for t in mqtt)
    buttons = next(t for t in triggers if isinstance(t.get("entity_id"), list))
    assert set(buttons["entity_id"]) == {"input_button.coffee_stop", "input_button.coffee_acknowledge_fault"}
    event = next(t for t in triggers if t["trigger"] == "event")
    assert event["event_data"]["action"] == "COFFEE_STOP"
    # The OFF is inline (never depends on a script); confirmation is shared.
    assert auto["action"][0] == {"continue_on_error": True, "action": "switch.turn_off",
                                 "target": {"entity_id": PLUG}}
    assert auto["action"][1]["action"] == "script.coffee_confirm_off"
    assert "unconfirmed_message" in auto["action"][1]["data"]
    assert auto["mode"] == "queued"


def test_confirm_off_script_waits_then_alerts_or_notifies():
    seq = _package()["script"]["coffee_confirm_off"]["sequence"]
    assert seq[0]["timeout"] == "00:00:30" and seq[0]["continue_on_timeout"] is True
    branch = seq[1]
    assert branch["if"][0] == {"condition": "state", "entity_id": PLUG, "state": "off"}
    assert branch["then"][0]["then"][0]["action"] == "script.coffee_fault_notice"
    assert branch["else"][0]["action"] == "script.coffee_unplug_alert"


def test_fault_notice_is_time_sensitive_with_dashboard_link():
    data = _package()["script"]["coffee_fault_notice"]["sequence"][0]["data"]["data"]
    assert data["push"]["interruption-level"] == "time-sensitive"
    assert data["tag"] == "coffee_station_fault"
    assert data["url"] == data["clickAction"] == "/db-coffee/coffee"


def test_watchdog_covers_runtime_dropout_and_phantom_power():
    auto = _automation("coffee_max_on_watchdog")
    by_id = {t["id"]: t for t in auto["trigger"]}
    assert by_id["max_on"]["for"] == "00:15:00"
    assert _app_block()["max_energized_s"] < 15 * 60
    assert by_id["dropped_while_on"]["from"] == "on" and by_id["dropped_while_on"]["to"] == "unavailable"
    # Combined condition (power high AND switch not on) sustained, so a switch
    # flipping to off while power is already high still starts the timer.
    phantom = by_id["power_while_off"]
    assert phantom["trigger"] == "template" and phantom["for"] == "00:02:00"
    assert "sensor.coffee_maker_power" in phantom["value_template"]
    assert "is_state('switch.coffee_maker', 'on')" in phantom["value_template"]
    branches = {b["conditions"][0]["id"]: b["sequence"] for b in auto["action"][0]["choose"]}
    assert branches["max_on"][0]["action"] == "switch.turn_off"
    assert branches["max_on"][1]["action"] == "script.coffee_confirm_off"
    assert branches["max_on"][1]["data"]["confirmed_message"]
    assert branches["dropped_while_on"][0]["action"] == "script.coffee_unplug_alert"
    assert [s["action"] for s in branches["power_while_off"]] == ["switch.turn_off", "script.coffee_unplug_alert"]


def test_every_yaml_off_step_continues_to_confirmation_on_error():
    """A failed OFF service call (e.g. Matter timeout) must not abort the
    confirmation and the critical unplug alert that follow it."""
    pkg = _package()
    offs = [n for n in _walk(pkg["automation"]) if n.get("action") == "switch.turn_off"]
    assert len(offs) == 4
    assert all(n.get("continue_on_error") is True for n in offs)


def test_startup_shutoff_waits_confirms_and_reports_timeout():
    auto = _automation("coffee_startup_shutoff")
    assert auto["trigger"][0] == {"trigger": "homeassistant", "event": "start"}
    assert auto["action"][0]["continue_on_timeout"] is True
    on_branch, unknown_branch = auto["action"][1]["choose"]
    assert on_branch["sequence"][0]["action"] == "switch.turn_off"
    assert on_branch["sequence"][1]["action"] == "script.coffee_confirm_off"
    assert unknown_branch["sequence"][0]["action"] == "script.coffee_fault_notice"


def test_helpers_exist_for_every_app_reference():
    pkg = _package()
    app = _app_block()
    helpers = {f"{domain}.{key}" for domain in ("input_button", "counter", "input_number", "input_datetime")
               for key in pkg[domain]}
    for arg in ("arm_button", "brew_now_button", "stop_button", "acknowledge_button", "reset_maintenance_button",
                "total_brews_counter", "brews_since_descale_counter", "failed_brews_counter", "last_brew_entity",
                "last_descale_entity", "last_brew_duration_entity", "last_brew_energy_entity",
                "last_brew_peak_power_entity"):
        assert app[arg] in helpers, arg
    assert all(c.get("restore") is True for c in pkg["counter"].values())
    assert all("initial" not in v for v in pkg["input_number"].values()), "initial would wipe restored metrics"


def test_app_config_uses_commissioned_names_and_private_presence():
    app = _app_block()
    text = (ROOT / "private_templates" / "appdaemon_apps.yaml.tmpl").read_text(encoding="utf-8")
    assert "presence_entity: binary_sensor.bayesian_@@PRIVATE:presence_person_slug@@_home" in text
    assert app["switch_entity"] == PLUG
    assert app["remote_action_entity"] == REMOTE
    assert app["bed_entity"] == "input_boolean.master_bed_occupancy"
    assert app["notify_service"] == "notify/all"
    assert app["max_auto_brews"] == 1
    combined = (ROOT / "packages" / "coffee.yaml").read_text() + text.split("\ncoffee_station:", 1)[1]
    # No hardware identifiers: Zigbee IEEE addresses or the plug's raw entity ids.
    assert not re.search(r"0x[0-9a-f]{16}", combined)
    assert "eve_energy_" not in combined


def test_app_module_is_tracked_by_git():
    assert "!appdaemon/apps/coffee_station.py" in (ROOT / ".gitignore").read_text()


def test_dashboard_registered_and_stop_always_visible():
    config = (ROOT / "configuration.yaml").read_text()
    assert "filename: lovelace/dashboards/coffee.yaml" in config
    dash = _load(ROOT / "lovelace" / "dashboards" / "coffee.yaml")
    cards = [c for section in dash["views"][0]["sections"] for c in section["cards"]]
    by_entity = {}
    for card in cards:
        by_entity.setdefault(card.get("entity"), []).append(card)
    stop = by_entity["input_button.coffee_stop"][0]
    assert "visibility" not in stop
    assert stop["tap_action"]["perform_action"] == "input_button.press"
    arm = by_entity["input_button.coffee_arm"][0]
    assert set(arm["visibility"][0]["state"]) == {"idle", "ready", "cancelled"}
    brew = by_entity["input_button.coffee_brew_now"][0]
    assert set(brew["visibility"][0]["state"]) == {"armed", "waiting_for_wakeup"}
    ack = by_entity["input_button.coffee_acknowledge_fault"][0]
    assert ack["visibility"][0]["state"] == "fault"
    pkg = _package()
    for entity in by_entity:
        if entity and entity.split(".")[0] in ("input_button", "counter", "input_number", "input_datetime"):
            domain, key = entity.split(".")
            assert key in pkg[domain], entity
