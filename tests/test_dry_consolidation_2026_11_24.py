"""Regression tests for the 2026-11-24 DRY consolidation (desk, Inovelli, weather)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DESK_TEMPLATE = ROOT / "private_templates" / "desk.yaml.tmpl"
ZIGBEE = ROOT / "packages" / "zigbee_zwave.yaml"
WEATHER_TEMPLATE = ROOT / "packages" / "weather.yaml"  # rendered from private_templates


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!secret", lambda loader, node: f"!secret {node.value}")
_Loader.add_multi_constructor("!include", lambda loader, suffix, node: None)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


def _automation(path: Path, automation_id: str) -> dict:
    for automation in _load(path)["automation"]:
        if automation.get("id") == automation_id:
            return automation
    raise AssertionError(f"{automation_id} not found in {path.name}")


def _choose_aliases(choose: list[dict]) -> list[str]:
    return [option["alias"] for option in choose]


def test_desk_has_one_policy_automation_in_priority_order() -> None:
    automations = _load(DESK_TEMPLATE)["automation"]
    assert [a["id"] for a in automations] == ["uplift_desk_policy"]

    policy = automations[0]
    assert policy["mode"] == "queued"
    trigger_ids = {t["id"] for t in policy["trigger"]}
    assert trigger_ids == {
        "guest_mode",
        "trip_mode",
        "work_camera",
        "departed",
        "arrived",
        "evening",
        "monday_reset",
    }

    options = policy["action"][0]["choose"]
    assert _choose_aliases(options) == [
        "Guest mode: highest priority",
        "Trip mode unless guest mode",
        "Work camera unless guest or trip mode",
        "Presence and timed moves: no higher-priority mode active",
    ]
    # Guest mode is unconditional; each lower tier is blocked by every higher one.
    assert options[0]["conditions"] == [{"condition": "trigger", "id": "guest_mode"}]
    assert options[1]["conditions"][1]["entity_id"] == "input_boolean.guest_mode"
    assert options[2]["conditions"][1]["entity_id"] == [
        "input_boolean.guest_mode",
        "input_boolean.trip",
    ]
    assert options[3]["conditions"][1]["entity_id"] == [
        "input_boolean.guest_mode",
        "input_boolean.trip",
        "binary_sensor.f7m69c_5d3d6e76_camera_in_use",
    ]
    targets = [opt["sequence"][0]["action"] for opt in options[3]["sequence"][0]["choose"]]
    assert targets == [
        "script.uplift_desk_auto_move_max",
        "script.uplift_desk_auto_move_preset_1",
        "script.uplift_desk_auto_move_max",
        "script.uplift_desk_auto_move_preset_1",
    ]


def test_inovelli_reset_bulk_settings_are_table_driven() -> None:
    script = _load(ZIGBEE)["script"]["reset_inovelli_switches"]
    settings = {s["name"]: s for s in script["variables"]["inovelli_bulk_settings"]}

    assert set(settings) == {
        "active_energy_report_rate",
        "active_power_report_rate",
        "energy_report_rate",
        "double_tap_up_mode",
        "double_tap_up_brightness",
        "singletapbehavior_mode",
        "bindingofftoonsynclevel_mode",
    }
    assert settings["double_tap_up_brightness"]["value"] == 254
    assert settings["singletapbehavior_mode"]["option"] == "Old Behavior"
    assert settings["singletapbehavior_mode"]["exclude"] == [
        "exhaust",
        "fan_switch",
        "overhead_outlet",
    ]
    assert not any(k.startswith("all_inovelli_switches_") for k in script["variables"])


def test_weather_alerts_use_one_notify_all_path() -> None:
    text = WEATHER_TEMPLATE.read_text(encoding="utf-8")
    ids = [a["id"] for a in _load(WEATHER_TEMPLATE)["automation"]]

    assert "notify_tornado_warning_alert" not in ids
    assert "weather_alerts_pushbullet_notification_1" not in ids
    assert "notify.notify_all" not in text

    alert = _automation(WEATHER_TEMPLATE, "notify_weather_alert")
    options = next(step for step in alert["action"] if "choose" in step)["choose"]
    tornado, other = options
    assert tornado["sequence"][-1]["action"] == "notify.all"
    assert tornado["sequence"][-1]["data"]["data"]["push"]["sound"]["critical"] == 1
    assert other["sequence"][0]["action"] == "notify.all"


def test_weather_alert_pushes_each_new_alert_id_not_just_the_first() -> None:
    """Codex P1 on #1264: a numeric_state "above 0" trigger only fires on the
    0 -> N edge, so a warning arriving while another alert was active (the
    2026-10-28 Tornado Warning, 3rd active alert) never pushed."""
    alert = _automation(WEATHER_TEMPLATE, "notify_weather_alert")

    assert alert["mode"] == "queued"
    assert alert["trigger"] == [
        {
            "trigger": "state",
            "entity_id": "sensor.nws_alerts",
            "not_to": ["unavailable", "unknown"],
        }
    ]
    variables = alert["action"][0]["variables"]
    assert "input_text.nws_alerts_notified_ids" in variables["notified_ids"]
    assert "not in notified_ids" in variables["new_alerts"]
    # Live NWS code for a Tornado Warning is TOW; only *new* alerts can escalate.
    assert "['TOR', 'TOW']" in variables["tornado_alerts"]
    assert variables["tornado_alerts"].count("new_alerts") == 2

    # Stop before pushing unless something is new; record IDs before the push.
    steps = alert["action"]
    assert steps[1]["condition"] == "template"
    assert "new_alerts | count > 0" in steps[1]["value_template"]
    assert steps[2]["action"] == "input_text.set_value"
    assert steps[2]["target"]["entity_id"] == "input_text.nws_alerts_notified_ids"

    helper = _load(WEATHER_TEMPLATE)["input_text"]["nws_alerts_notified_ids"]
    assert helper["max"] == 255
    assert "initial" not in helper  # restores across restarts: no re-push on reboot
