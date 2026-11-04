from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import jinja2
import pytest
import yaml

from scripts.calm_dashboard import READINESS, build_dashboard, entity_references, normalize_card

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=TZ)


class States:
    def __init__(self, values, attrs):
        self.values, self.attrs = values, attrs

    def __call__(self, entity):
        return self.values.get(entity, "unknown")

    def __getitem__(self, entity):
        return SimpleNamespace(state=self(entity), attributes=self.attrs.get(entity, {}), last_updated=NOW)


def render(macro, *, values=None, attrs=None, now=NOW, args=()):
    values = {"input_number.pre_arrival_clean_lead_minutes": "240",
              "input_number.pre_arrival_clean_buffer_minutes": "30", **(values or {})}
    attrs = attrs or {}

    def as_datetime(value, default=None):
        if isinstance(value, datetime):
            return value
        try:
            if isinstance(value, (float, int)):
                return datetime.fromtimestamp(value, TZ)
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)
        except (ValueError, TypeError):
            return default

    def as_timestamp(value, default=None):
        parsed = as_datetime(value)
        return parsed.timestamp() if parsed else default

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / "custom_templates"), undefined=jinja2.StrictUndefined)
    env.filters.update(to_json=json.dumps, from_json=json.loads, as_datetime=as_datetime, as_local=lambda d: d.astimezone(TZ))
    env.globals.update(states=States(values, attrs), is_state=lambda e, s: values.get(e) == s,
                       state_attr=lambda e, a: attrs.get(e, {}).get(a),
                       has_value=lambda e: values.get(e, "unknown") not in ["unknown", "unavailable"],
                       as_datetime=as_datetime, as_timestamp=as_timestamp, now=lambda: now)
    result = getattr(env.get_template("dashboard_status.jinja").module, macro)(*args).strip()
    return json.loads(result) if result.startswith("{") else result


def report(kind, values=None, attrs=None):
    return render("readiness", values=values, attrs=attrs, args=(kind,))


@pytest.mark.parametrize("mode,trip,extra,expected", [
    ("home", "off", {}, "home"), ("home", "on", {}, "away"),
    ("asleep", "off", {}, "sleep"), ("night", "off", {}, "evening"),
    ("asleep", "on", {"binary_sensor.pre_arrival_clean_day": "on"}, "return"),
    ("home", "on", {"binary_sensor.flying_home_today": "on"}, "return"),
    ("away", "off", {}, "away"), ("unavailable", "off", {}, "unknown"),
    ("home", "unavailable", {}, "unknown"),
])
def test_context_precedence(mode, trip, extra, expected):
    assert render("context", values={"input_select.house_mode": mode, "input_boolean.trip": trip, **extra}) == expected


def test_context_uses_home_date_and_ignores_future_itinerary():
    values = {"input_select.house_mode": "home", "input_boolean.trip": "off"}
    attrs = {"sensor.ecobee_calendar_vacation_schedule": {"start": "2026-11-03T02:00:00+00:00"}}
    assert render("context", values=values, attrs=attrs) == "departure"  # 8PM home time today.
    attrs["sensor.ecobee_calendar_vacation_schedule"]["start"] = "2027-03-04T12:00:00-06:00"
    assert render("context", values=values, attrs=attrs) == "home"
    assert render("context", values=values, now=NOW.replace(hour=8)) == "morning"
    assert render("context", values=values, now=NOW.replace(hour=12)) == "home"


def test_context_does_not_replace_sleep_with_departure():
    assert render("context", values={"input_select.house_mode": "asleep", "input_boolean.trip": "off"},
                  attrs={"sensor.ecobee_calendar_vacation_schedule": {"start": NOW.replace(hour=20).isoformat()}}) == "sleep"


@pytest.fixture
def cycle_attrs():
    return {"cycle_id": NOW.replace(hour=18).isoformat(), "landing_at": NOW.replace(hour=18).isoformat(),
            "window_start": NOW.replace(hour=14).isoformat(), "finish_by": NOW.replace(hour=17, minute=30).isoformat(),
            "trip_started_at": (NOW - timedelta(days=3)).isoformat(), "closed_at": ""}


def event(entity="sensor.next_flight_home_arrival", old="off", new="on"):
    return SimpleNamespace(platform="state", entity_id=entity,
                           from_state=SimpleNamespace(state=old), to_state=SimpleNamespace(state=new))


def test_cycle_missing_trip_signal_does_not_close_restored_cycle(cycle_attrs):
    result = render("cycle", values={"input_boolean.trip": "unavailable"},
                    args=(cycle_attrs, SimpleNamespace(platform="homeassistant")))
    assert result == cycle_attrs


def test_new_landing_does_not_capture_previous_dependent_sensor_window(cycle_attrs):
    landing = NOW + timedelta(days=1)
    values = {"input_boolean.trip": "on", "sensor.next_flight_home_arrival": landing.isoformat(),
              "sensor.pre_arrival_clean_start": cycle_attrs["window_start"],
              "sensor.pre_arrival_clean_finish_by": cycle_attrs["finish_by"]}
    result = render("cycle", values=values, args=(cycle_attrs, event()))
    assert result["cycle_id"] == landing.isoformat()
    assert result["window_start"] == (landing - timedelta(hours=4)).isoformat()
    assert result["finish_by"] == (landing - timedelta(minutes=30)).isoformat()
    values["sensor.pre_arrival_clean_start"] = result["window_start"]
    values["sensor.pre_arrival_clean_finish_by"] = result["finish_by"]
    assert render("cycle", values=values, args=(result, event())) == result
    attrs = {"sensor.dashboard_return_cycle": result}
    old_success = {"input_datetime.x40_ultra_last_vacuumed_at": NOW.replace(hour=14, minute=30).isoformat()}
    assert report("vacuum_main", old_success, attrs)["status"] != "complete"
    values["input_number.pre_arrival_clean_lead_minutes"] = "unavailable"
    unknown = render("cycle", values=values, args=(cycle_attrs, event()))
    assert unknown["window_start"] == "" and unknown["finish_by"] == ""


def test_cycle_delayed_flight_preserves_identity_and_window(cycle_attrs):
    values = {"input_boolean.trip": "on", "sensor.next_flight_home_arrival": NOW.replace(hour=19).isoformat(),
              "sensor.pre_arrival_clean_start": NOW.replace(hour=15).isoformat(),
              "sensor.pre_arrival_clean_finish_by": NOW.replace(hour=18, minute=30).isoformat()}
    result = render("cycle", values=values, args=(cycle_attrs, event()))
    assert result["cycle_id"] == cycle_attrs["cycle_id"]
    assert result["window_start"] == cycle_attrs["window_start"]
    assert result["landing_at"] == values["sensor.next_flight_home_arrival"]


def test_cycle_survives_landing_missing_itinerary_and_restart(cycle_attrs):
    result = render("cycle", values={"input_boolean.trip": "on"}, args=(cycle_attrs, SimpleNamespace(platform="homeassistant")))
    assert result == cycle_attrs
    future = {"input_boolean.trip": "on", "sensor.next_flight_home_arrival": "2027-03-15T15:00:00-05:00",
              "sensor.pre_arrival_clean_start": "2027-03-15T11:00:00-05:00", "sensor.pre_arrival_clean_finish_by": "2027-03-15T14:30:00-05:00"}
    assert render("cycle", values=future, now=NOW.replace(hour=20), args=(cycle_attrs, event())) == cycle_attrs


def test_new_trip_invalidates_previous_cycle(cycle_attrs):
    result = render("cycle", values={"input_boolean.trip": "on"}, args=(cycle_attrs, event("input_boolean.trip")))
    assert result["cycle_id"] == ""
    assert result["window_start"] == ""
    assert result["trip_started_at"] == NOW.isoformat()


def test_completed_trip_freezes_evidence_window(cycle_attrs):
    result = render("cycle", values={"input_boolean.trip": "off"}, args=(cycle_attrs, event("input_boolean.trip", "on", "off")))
    assert result["closed_at"] == NOW.isoformat()
    attrs = {"sensor.dashboard_return_cycle": result}
    assert report("vacuum_main", {"input_datetime.x40_ultra_last_vacuumed_at": NOW.replace(hour=16).isoformat()}, attrs)["status"] != "complete"


def test_large_flight_change_creates_new_cycle(cycle_attrs):
    landing = NOW + timedelta(days=2)
    values = {"input_boolean.trip": "on", "sensor.next_flight_home_arrival": landing.isoformat(),
              "sensor.pre_arrival_clean_start": (landing - timedelta(hours=4)).isoformat(),
              "sensor.pre_arrival_clean_finish_by": (landing - timedelta(minutes=30)).isoformat()}
    result = render("cycle", values=values, args=(cycle_attrs, event()))
    assert result["cycle_id"] == landing.isoformat()
    assert result["window_start"] != cycle_attrs["window_start"]


def test_main_completion_requires_current_cycle_success_timestamp(cycle_attrs):
    attrs = {"sensor.dashboard_return_cycle": cycle_attrs}
    common = {"input_boolean.guest_mode": "off", "input_boolean.trip_guest_visit_active": "off", "vacuum.x40_ultra": "docked"}
    for kind, entity in [("vacuum_main", "input_datetime.x40_ultra_last_vacuumed_at"), ("mop_main", "input_datetime.x40_ultra_last_mopped_at")]:
        assert report(kind, {**common, entity: (NOW - timedelta(days=1)).isoformat()}, attrs)["status"] == "unknown"
        assert report(kind, {**common, entity: NOW.replace(hour=14, minute=30).isoformat()}, attrs)["status"] == "complete"
        assert report(kind, {**common, entity: NOW.replace(hour=19).isoformat()}, attrs)["status"] != "complete"


@pytest.mark.parametrize("values,expected", [
    ({"input_boolean.guest_mode": "on"}, "blocked"),
    ({"input_boolean.trip_guest_visit_active": "on"}, "blocked"),
    ({"input_boolean.guest_mode": "unavailable"}, "unknown"),
    ({"script.x40_ultra_main_level_mop_only": "on", "input_boolean.x40_ultra_active_run_owned": "on"}, "running"),
    ({"script.x40_ultra_main_level_mop_only": "on", "input_boolean.x40_ultra_active_run_owned": "off"}, "unknown"),
    ({"vacuum.x40_ultra": "unavailable"}, "unknown"),
])
def test_interruption_privacy_and_owned_run_reporting(cycle_attrs, values, expected):
    common = {"input_boolean.guest_mode": "off", "input_boolean.trip_guest_visit_active": "off", "vacuum.x40_ultra": "docked"}
    assert report("mop_main", {**common, **values}, {"sensor.dashboard_return_cycle": cycle_attrs})["status"] == expected


def test_deadline_and_future_window(cycle_attrs):
    attrs = {"sensor.dashboard_return_cycle": cycle_attrs}
    common = {"input_boolean.guest_mode": "off", "input_boolean.trip_guest_visit_active": "off", "vacuum.x40_ultra": "docked"}
    assert render("readiness", values=common, attrs=attrs, now=NOW.replace(hour=18), args=("mop_main",))["status"] == "unknown"
    assert render("readiness", values=common, attrs=attrs, now=NOW.replace(hour=13), args=("mop_main",))["status"] == "scheduled"


@pytest.mark.parametrize("kind,entity", [("vacuum_den", "vacuum.valetudo_den"), ("vacuum_upstairs", "sensor.dashboard_upstairs_activity")])
def test_secondary_docking_is_not_completion(kind, entity):
    assert report(kind, {entity: "docked"})["status"] == "unknown"
    assert report(kind, {entity: "cleaning"})["status"] == "running"
    assert report(kind, {entity: "error"})["status"] == "blocked"


def test_climate_has_no_invented_target_or_success():
    assert report("climate", {"climate.my_ecobee": "off"}, {"climate.my_ecobee": {"current_temperature": 70}})["status"] == "unknown"
    assert report("climate", {"climate.my_ecobee": "heat"}, {"climate.my_ecobee": {"current_temperature": 70}})["status"] == "unknown"
    attrs = {"climate.my_ecobee": {"current_temperature": 70, "temperature": 70}}
    assert report("climate", {"climate.my_ecobee": "heat"}, attrs)["status"] == "complete"
    attrs["climate.my_ecobee"]["current_temperature"] = 65
    assert report("climate", {"climate.my_ecobee": "heat"}, attrs)["status"] == "running"
    attrs["climate.my_ecobee"] = {"current_temperature": 70, "target_temp_low": 68, "target_temp_high": 72}
    assert report("climate", {"climate.my_ecobee": "heat_cool"}, attrs)["status"] == "complete"


def test_water_reports_device_state_and_existing_restore_timing():
    leaks = {e: "off" for e in ["binary_sensor.basement_unfinished_leak_water_leak", "binary_sensor.kitchen_sink_leak_water_leak", "binary_sensor.laundry_room_leak_water_leak"]}
    values = {**leaks, "switch.basement_water_shutoff": "off", "input_boolean.trip": "on"}
    result = report("water", values)
    assert result["status"] == "scheduled" and "trip-end" in result["reason"]
    assert report("water", {**values, "input_boolean.trip": "off"})["status"] == "blocked"
    assert "not independently" in report("water", {**values, "switch.basement_water_shutoff": "on"})["reason"]
    assert report("water", {**values, "binary_sensor.kitchen_sink_leak_water_leak": "on"})["status"] == "blocked"
    assert report("water", {"switch.basement_water_shutoff": "on"})["status"] == "unknown"


def test_security_guest_and_alarm_states():
    values = {"lock.front_door_lock": "locked", "cover.garage_door": "closed", "alarm_control_panel.home_alarm": "disarmed"}
    assert report("security", values)["status"] == "complete"
    assert report("security", {**values, "input_boolean.trip": "on"})["status"] == "blocked"
    assert report("security", {**values, "input_boolean.trip_guest_visit_active": "on"})["status"] == "running"
    assert report("security", {**values, "alarm_control_panel.home_alarm": "triggered"})["status"] == "blocked"
    assert report("security", {**values, "cover.garage_door": "unavailable"})["status"] == "unknown"


def test_feeding_schedule_never_claims_success():
    values = {"binary_sensor.main_level_cat_feeder_error": "off", "binary_sensor.upstairs_cat_feeder_error": "off",
              "select.main_level_cat_feeder_mode": "schedule", "select.upstairs_cat_feeder_mode": "schedule"}
    assert report("pet_care", values)["status"] == "unknown"
    assert report("pet_care", {**values, "binary_sensor.main_level_cat_feeder_error": "on"})["status"] == "blocked"


def test_aggregate_cannot_hide_unknown_or_missing_results():
    values = {"sensor.dashboard_readiness_" + key: "complete" for key, _ in READINESS}
    assert render("aggregate", values=values) == "complete"
    for status in ["unknown", "unavailable", "skipped", "scheduled", "running", "blocked"]:
        assert render("aggregate", values={**values, "sensor.dashboard_readiness_pet_care": status}) != "complete"


@pytest.fixture
def original():
    return {"other_setting": {"keep": True}, "button_card_templates": {"existing": {"show_name": False}},
            "views": [{"title": "Home", "cards": []},
                      {"title": "Owner Suite", "path": "owner-suite", "type": "sections", "sections": []},
                      {"title": "Specialist", "path": "specialist", "cards": [{"type": "sensor", "entity": "sensor.example"}]}]}


def test_composition_preserves_indices_paths_and_unrelated_content(original):
    before = deepcopy(original)
    result = build_dashboard(original, "/example-dashboard")
    assert original == before
    assert [v["path"] for v in result["views"]] == ["home", "owner-suite", "specialist", "rooms", "house", "travel", "more"]
    assert result["other_setting"] == before["other_setting"]
    assert result["button_card_templates"]["existing"] == before["button_card_templates"]["existing"]
    assert result["views"][2]["cards"][0] == before["views"][2]["cards"][0]
    assert result["views"][1]["back_path"] == "/example-dashboard/rooms"


def test_reapplying_does_not_duplicate_views_or_navigation(original):
    once = build_dashboard(original, "/example-dashboard")
    twice = build_dashboard(once, "/example-dashboard")
    assert len(twice["views"]) == len(once["views"])
    assert len(twice["views"][2]["cards"]) == 2


def test_normalization_preserves_specialist_controls_and_actions():
    original = {"type": "custom:mini-media-player", "entity": "media_player.ma_bedroom", "speaker_group": {"entities": []}}
    assert normalize_card(original) == original
    original = {"type": "custom:mushroom-light-card", "entity": "light.example", "show_brightness_control": True,
                "tap_action": {"action": "navigate", "navigation_path": "/example"}}
    converted = normalize_card(original)
    assert converted["tap_action"] == original["tap_action"]
    assert converted["features"] == [{"type": "light-brightness"}]


def test_package_observers_are_read_only_and_replay_does_not_refresh_evidence():
    package = yaml.safe_load((ROOT / "packages/dashboard_status.yaml").read_text())
    assert set(package) == {"template"}
    assert not any("actions" in block or "action" in block for block in package["template"])
    observer = package["template"][1]
    assert observer["triggers"][0]["topic"] == "valetudo/upstairs-vacuum/StatusStateAttribute/status"
    expression = observer["sensor"][0]["attributes"]["observed_at"]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    value = env.from_string(expression).render(this=SimpleNamespace(state="cleaning", attributes={"observed_at": "older"}),
                                               trigger=SimpleNamespace(payload="cleaning"), now=lambda: NOW)
    assert value == "older"


def test_new_ui_references_and_private_fixture_contract(original):
    result = build_dashboard(original, "/example-dashboard")
    refs = entity_references(result)
    assert "sensor.dashboard_readiness_water" in refs
    assert "media_player.ma_bedroom" in refs
    assert not any("_sonos" in e for e in refs)
    for primary in ["home", "rooms", "house", "travel", "more"]:
        v = next(v for v in result["views"] if v.get("path") == primary)
        assert v["sections"][0]["column_span"] == 4
        assert v["sections"][0]["cards"][0]["grid_options"]["columns"] == "full"
        assert v["footer"]["card"]["desktop"]["min_width"] == 1200
        assert v["footer"]["card"]["mobile"]["safe_area"]
        assert v["subview"] is False


def test_rooms_and_fan_use_accessible_native_controls(original):
    result = build_dashboard(original, "/example-dashboard")
    rooms = next(v for v in result["views"] if v.get("path") == "rooms")
    grid = rooms["sections"][1]["cards"][1]
    assert grid["type"] == "grid" and grid["columns"] == 2
    room = grid["cards"][0]
    assert room["type"] == "custom:mushroom-template-card"
    assert room["icon_tap_action"]["action"] == "none"
    assert room["tap_action"]["action"] == "navigate"
    quick = result["views"][0]["sections"][-1]["cards"][1]["cards"]
    fan = next(c for c in quick if c.get("entity") == "fan.owner_suite")
    assert fan["tap_action"]["action"] == "more-info"


def test_missing_critical_monitoring_is_visible_independent_of_context(original):
    home = build_dashboard(original, "/example-dashboard")["views"][0]
    exceptions = next(s for s in home["sections"] if s["cards"][0].get("heading") == "Needs attention")
    for kind in ["security", "water"]:
        card = next(c for c in exceptions["cards"] if c.get("entity") == f"sensor.dashboard_readiness_{kind}")
        assert card["visibility"][0]["state"] == ["blocked", "unknown"]
        assert card["visibility"][0] in exceptions["visibility"][0]["conditions"]


def test_unavailable_device_alerts_identify_each_affected_device(original):
    home = build_dashboard(original, "/example-dashboard")["views"][0]
    exceptions = next(s for s in home["sections"] if s["cards"][0].get("heading") == "Needs attention")
    names = {c["entity"]: c["primary"] for c in exceptions["cards"] if "entity" in c}
    assert names["fan.owner_suite"] == "Owner-suite ceiling fan"
    assert names["light.owner_suite_lamps"] == "Owner-suite lamps"
    assert names["cover.owner_suite_blinds_ha"] == "Owner-suite blinds"
    assert names["media_player.ma_bedroom"] == "Bedroom audio"


def test_home_matches_rooms_first_render_hierarchy(original):
    home = build_dashboard(original, "/example-dashboard")["views"][0]
    assert home["max_columns"] == 2
    rooms = home["sections"][1]
    assert rooms["cards"][0]["heading"] == "Your rooms"
    assert rooms["cards"][1]["columns"] == 2
    assert [r["primary"] for r in rooms["cards"][1]["cards"]] == ["Owner suite", "Office", "Kitchen", "Den"]
    for section in home["sections"][2:4]:
        assert section["cards"][0]["type"] == "grid"
        assert section["cards"][0]["columns"] == 1
    assert home["sections"][-1]["cards"][0]["heading"] == "Quick controls"


def test_room_summary_uses_reported_values_without_missing_temperature_as_zero():
    from scripts.calm_dashboard import ROOMS, room_card
    card = room_card(ROOMS[0], "/example-dashboard")
    values = {"light.owner_suite_lamps": "on", "cover.owner_suite_blinds_ha": "closed", "sensor.bedroom_temperature_2": "70"}
    attrs = {"light.owner_suite_lamps": {"brightness": 128}}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.globals.update(entity=card["entity"], states=States(values, attrs), state_attr=lambda e, a: attrs.get(e, {}).get(a))
    text = env.from_string(card["secondary"]).render()
    assert "Lamps 50%" in text and "Blinds closed" in text and "70°" in text
    values.update({"light.owner_suite_lamps": "unavailable", "sensor.bedroom_temperature_2": "unavailable"})
    text = env.from_string(card["secondary"]).render()
    assert "Lamps unavailable" in text and "0°" not in text


def test_idle_cached_media_title_is_not_presented_as_playing(original):
    home = build_dashboard(original, "/example-dashboard")["views"][0]
    audio = home["sections"][2]["cards"][0]["cards"][0]
    attrs = {audio["entity"]: {"media_title": "Previous track"}}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.globals.update(entity=audio["entity"], states=States({audio["entity"]: "idle"}, attrs),
                       state_attr=lambda e, a: attrs.get(e, {}).get(a))
    assert env.from_string(audio["secondary"]).render() == "Idle · Previous track"
    volume = home["sections"][2]["cards"][0]["cards"][1]
    assert volume["tap_action"]["action"] == "none"
    assert volume["icon_tap_action"]["action"] == "none"


def test_travel_checklist_is_one_panel_and_supply_controls_stay_explicit(original):
    travel = next(v for v in build_dashboard(original, "/example-dashboard")["views"] if v.get("path") == "travel")
    checklist = next(s for s in travel["sections"] if s["cards"][0].get("heading") == "Arrival readiness")
    rows = checklist["cards"][1]["cards"]
    assert len(rows) == len(READINESS)
    assert all(c["type"] == "custom:mushroom-template-card" for c in rows)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    for row in rows:
        assert env.from_string(row["icon"]).render(entity=row["entity"], states=lambda e: "unknown") == "mdi:help-circle-outline"
    controls = next(s for s in travel["sections"] if s["cards"][0].get("heading") == "Security and water")
    for card in controls["cards"][1]["cards"]:
        if card.get("entity") in {"lock.front_door_lock", "cover.garage_door", "switch.basement_water_shutoff"}:
            assert card["icon_tap_action"]["action"] == "more-info"


@pytest.mark.parametrize("root", ["relative", "/ends-with-slash/"])
def test_invalid_root_is_rejected(original, root):
    with pytest.raises(ValueError):
        build_dashboard(original, root)


def test_missing_home_is_rejected():
    with pytest.raises(ValueError):
        build_dashboard({"views": []}, "/example-dashboard")
    with pytest.raises(ValueError):
        build_dashboard({"views": [{"title": "Unrelated"}]}, "/example-dashboard")


@pytest.mark.parametrize("wrapped", [False, True])
def test_cli_preserves_envelope_and_limits_output_permissions(original, tmp_path, monkeypatch, wrapped):
    import sys
    from scripts.calm_dashboard import main
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    inventory = tmp_path / "states.json"
    source.write_text(json.dumps({"data": {"config": original}} if wrapped else original))
    inventory.write_text(json.dumps([{"entity_id": "light.office_all", "state": "on"}]))
    monkeypatch.setattr(sys, "argv", ["calm_dashboard", "--input", str(source), "--output", str(target), "--states", str(inventory), "--root", "/example-dashboard"])
    main()
    rebuilt = json.loads(target.read_text())
    config = rebuilt["data"]["config"] if wrapped else rebuilt
    assert config["views"][0]["path"] == "home"
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind,feature", [("custom:mushroom-fan-card", "fan-speed"), ("custom:mushroom-cover-card", "cover-position")])
def test_fan_cover_features_and_horizontal_grid(kind, feature):
    item = {"type": kind, "entity": "fan.example" if "fan" in kind else "cover.example",
            "show_percentage_control": True, "show_position_control": True}
    assert normalize_card(item)["features"] == [{"type": feature}]
    assert normalize_card({"type": "horizontal-stack", "cards": [item]})["type"] == "grid"
    assert entity_references({"entity_id": ["light.one", "light.two"]}) == {"light.one", "light.two"}
