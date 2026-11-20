"""Exercise alert decisions rather than treating every summary edit as an alert."""

from pathlib import Path
import re

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _battery_automation(automation_id):
    config = yaml.safe_load((ROOT / "packages/batteries.yaml").read_text())
    return next(a for a in config["automation"] if a["id"] == automation_id)


def _state(summary, state="1"):
    return {"state": state, "attributes": {"summary": summary}}


@pytest.mark.parametrize("automation_id", ["notify_battery_dying_10", "notify_battery_dead"])
@pytest.mark.parametrize(
    "previous,current,expected",
    [
        (_state("" , "0"), _state("- sensor.a_battery: 9%"), True),
        (_state("- sensor.a_battery: 9%"), _state("- sensor.a_battery: 8%"), False),
        (_state("- sensor.a_battery: 8%"), _state("- sensor.a_battery: 9%"), False),
        (_state("- sensor.a_battery: 9%"), _state("- sensor.b_battery: 9%"), True),
        (_state("- sensor.a_battery: unavailable"), _state("- sensor.b_battery: unavailable"), True),
        (_state("- sensor.a_battery: 9%\n- sensor.b_battery: 8%"), _state("- sensor.a_battery: 9%"), False),
        (_state("- sensor.a_battery: 9%"), _state("", "0"), False),
        (_state("- sensor.a_battery: 9%"), _state("- sensor.b_battery: 8%\n- sensor.a_battery: 9%"), True),
        (_state("- sensor.a_battery: unavailable"), _state("- sensor.a_battery: unavailable"), False),
        (_state("- sensor.a_battery: 9%\n- sensor.b_battery: 8%"), _state("- sensor.b_battery: 8%\n- sensor.a_battery: 9%"), False),
        (None, _state("- sensor.a_battery: 9%"), False),
        (_state("", "unknown"), _state("- sensor.a_battery: 9%"), False),
        (_state("", "unavailable"), _state("- sensor.a_battery: 9%"), False),
        (_state("- sensor.a_battery: 9%"), _state("", "unavailable"), False),
    ],
)
def test_push_only_for_new_devices(previous, current, expected, automation_id):
    automation = _battery_automation(automation_id)
    conditions = automation["action"][0]["choose"][0]  # zero-count recovery
    assert conditions["sequence"][1]["data"]["message"] == "clear_notification"
    push = automation["action"][0]["default"][-1]["choose"][0]
    assert push["conditions"][0] == {"condition": "trigger", "id": "summary_change"}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["regex_findall"] = lambda value, pattern: re.findall(pattern, value)
    result = env.from_string(push["conditions"][1]["value_template"]).render(
        trigger={"from_state": previous, "to_state": current}
    ).strip()
    assert result == str(expected)


def test_early_warning_retains_local_notice_and_mobile_clear_only():
    automation = _battery_automation("notify_battery_dying_20")
    actions = automation["action"][0]
    assert actions["default"][-1]["action"] == "persistent_notification.create"
    assert actions["default"][-1]["data"]["notification_id"] == "low-battery-20"
    assert all(a["action"] != "notify.all" for a in actions["default"])
    assert actions["choose"][0]["sequence"][-1]["data"]["message"] == "clear_notification"


def test_routine_reports_stay_local_and_high_water_still_pushes():
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
    config = yaml.load((ROOT / "packages/utilities.yaml").read_text(), Loader=Loader)
    automations = {a["id"]: a for a in config["automation"]}
    for automation_id, notice_id in [
        ("notify_sump_runs", "sump-runtime-summary"),
        ("notify_weekly_energy_cost_summary", "weekly-energy-cost-summary"),
    ]:
        action = automations[automation_id]["action"][0]
        assert action["action"] == "persistent_notification.create"
        assert action["data"]["notification_id"] == notice_id
        assert "notify.all" not in str(automations[automation_id]["action"])
    for automation_id in ["notify_sump_pit_full", "notify_sump_pit_getting_full"]:
        assert automations[automation_id]["action"][0]["action"] == "notify.all"


def _load_package(name):
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
    return yaml.load((ROOT / "packages" / f"{name}.yaml").read_text(), Loader=Loader)


def _walk_actions(value):
    if isinstance(value, dict):
        if isinstance(value.get("action"), str):
            yield value
        for child in value.values():
            yield from _walk_actions(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_actions(child)


@pytest.mark.parametrize(
    "package,automation_id",
    [
        ("batteries", "notify_battery_dying_10"),
        ("batteries", "notify_battery_dead"),
        ("alerts", "water_leak_detected"),
        ("alerts", "motion_detected_on_trip"),
        ("alerts", "alarm_triggered_response"),
        ("car", "garage_door_reminder"),
        ("cleaning", "laundry_room_entry_reminder"),
        ("cleaning", "washer_reminder"),
        ("utilities", "notify_sump_pit_getting_full"),
        ("utilities", "notify_sump_pit_full"),
        ("weather", "alert_house_windows_open_pressure_dropping"),
        ("weather", "window_open_departure_rain_warning"),
        ("weather", "window_open_home_rain_warning"),
        ("water_softener", "notify_refill_salt"),
        ("water_softener", "water_softener_forecast_refill_reminder"),
    ],
)
def test_attention_alerts_have_cross_platform_links_and_uri_buttons(package, automation_id):
    config = _load_package(package)
    automation = next(a for a in config["automation"] if a["id"] == automation_id)
    notifications = [
        a for a in _walk_actions(automation)
        if a["action"].startswith(("notify.", "mobile_notify_service"))
        and a.get("data", {}).get("message") != "clear_notification"
    ]
    # Wet alerts have task controls; the dry recovery branch does not need them.
    if automation_id == "water_leak_detected":
        notifications = notifications[:1]
    assert notifications
    for notification in notifications:
        data = notification["data"]["data"]
        assert data["url"] == data["clickAction"]
        assert data["url"].startswith("/")
        assert 1 <= len(data["actions"]) <= 3  # Android's action limit.
        for button in data["actions"]:
            assert button["action"] == "URI"  # No unhandled event or device command.
            assert button["title"]
            assert button["uri"].startswith("/?more-info-entity-id=")
            rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
                button["uri"]
            ).render(trigger={"from_state": {"entity_id": "binary_sensor.example_leak"}})
            assert re.fullmatch(r"/\?more-info-entity-id=[a-z_]+\.[a-z0-9_]+", rendered)


def test_blind_diagnostics_keep_evidence_without_user_notifications():
    automation, = _load_package("blind_forensics")["automation"]
    assert automation["trace"]["stored_traces"] == 50
    assert [a["action"] for a in automation["actions"]] == ["logbook.log"]
    assert "trigger.to_state.context.id" in automation["actions"][0]["data"]["message"]


def test_local_persistent_notices_do_not_receive_mobile_only_data():
    for name in ["alerts", "batteries", "utilities"]:
        for action in _walk_actions(_load_package(name)):
            if action["action"] == "persistent_notification.create":
                assert set(action["data"]) <= {"title", "message", "notification_id"}
