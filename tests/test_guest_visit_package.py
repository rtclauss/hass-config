"""Guest (cat-sitter) entry while away: structure checks for issue #1088."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
ALERTS_PATH = ROOT / "packages" / "alerts.yaml"
TRAVIS_SECRETS_PATH = ROOT / "travis_secrets.yaml"


class _Loader(yaml.SafeLoader):
    pass


def _tagged(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> str:
    return f"{tag_suffix}:{loader.construct_scalar(node)}"


for _tag in ("!secret", "!include", "!include_dir_merge_named", "!include_dir_named"):
    _Loader.add_multi_constructor(_tag, lambda l, s, n: _tagged(l, s, n))
_Loader.add_constructor("!secret", lambda l, n: f"secret:{l.construct_scalar(n)}")


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


@pytest.fixture(scope="module")
def trips() -> dict:
    return _load(TRIPS_PATH)


@pytest.fixture(scope="module")
def alerts() -> dict:
    return _load(ALERTS_PATH)


def _automation(package: dict, automation_id: str) -> dict:
    for item in package["automation"]:
        if item.get("id") == automation_id:
            return item
    raise AssertionError(f"automation {automation_id!r} not found")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_new_automations_and_scripts_exist(trips: dict, alerts: dict) -> None:
    for automation_id in (
        "trip_garage_credentialed_open_starts_visit",
        "trip_guest_nfc_picture_tap",
        "trip_guest_visit_expiry",
        "trip_guest_visit_early_end",
        "trip_stale_disarm_rearm",
    ):
        item = _automation(trips, automation_id)
        assert item["alias"] == automation_id

    assert "trip_guest_visit_start" in trips["script"]
    assert "trip_guest_visit_end" in trips["script"]
    assert "alarm_strobe_until_resolved" in alerts["script"]
    assert "flash_entry_lights" in alerts["script"]


def test_nfc_webhooks_use_secrets_and_accept_get(trips: dict) -> None:
    item = _automation(trips, "trip_guest_nfc_picture_tap")
    triggers = item["trigger"]
    assert [t["id"] for t in triggers] == ["accept", "decoy", "decoy"]
    ids = [t["webhook_id"] for t in triggers]
    assert ids == [
        "secret:guest_tap_accept_webhook_id",
        "secret:guest_tap_decoy_a_webhook_id",
        "secret:guest_tap_decoy_b_webhook_id",
    ]
    assert len(set(ids)) == 3
    for trigger in triggers:
        # A phone reading a URL tag issues a GET.
        assert "GET" in trigger["allowed_methods"]
        assert trigger["local_only"] is False


def test_webhook_secrets_have_ci_placeholders() -> None:
    secrets = _load(TRAVIS_SECRETS_PATH)
    for key in (
        "guest_tap_accept_webhook_id",
        "guest_tap_decoy_a_webhook_id",
        "guest_tap_decoy_b_webhook_id",
    ):
        assert secrets[key]
    # Real ids must never be committed; placeholders only.
    assert all("placeholder" in str(secrets[k]) for k in secrets if k.startswith("guest_tap_"))


def test_picture_tap_requires_trip_and_away(trips: dict) -> None:
    item = _automation(trips, "trip_guest_nfc_picture_tap")
    entities = {c["entity_id"]: c["state"] for c in item["condition"]}
    assert entities == {
        "input_boolean.trip": "on",
        "binary_sensor.bayesian_zeke_home": "off",
    }


def test_accept_needs_something_to_answer_and_decoy_escalates() -> None:
    text = _text(TRIPS_PATH)
    assert "automation.motion_detected_on_trip" in text
    assert "< 1800" in text
    assert "script.alarm_strobe_until_resolved" in text
    assert "interruption-level: critical" in text


def test_visit_start_reuses_virtual_lock_flow(trips: dict) -> None:
    sequence = trips["script"]["trip_guest_visit_start"]["sequence"]
    text = yaml.dump(sequence)
    assert "lock.front_door_lock" in text
    assert "trip_guest_visit_open_house_requested" in text
    assert "automation.trip_guest_door_unlock_open_house" not in text
    # The evidence event must come AFTER the visit flag is on, or the expiry
    # automation's condition drops the first event and the visit never ends.
    kinds = [list(step)[0] for step in sequence]
    wait_index = next(i for i, s in enumerate(sequence) if "wait_template" in s)
    event_index = next(i for i, s in enumerate(sequence) if "event" in s)
    assert wait_index < event_index, kinds


def test_visit_end_reuses_close_house_flow(trips: dict) -> None:
    text = yaml.dump(trips["script"]["trip_guest_visit_end"]["sequence"])
    assert "lock.lock" in text
    assert "automation.trip_guest_door_lock_close_house" in text


def test_expiry_is_two_hours_with_restart_safe_four_hour_cap(trips: dict) -> None:
    item = _automation(trips, "trip_guest_visit_expiry")
    assert item["mode"] == "restart"
    cap = next(t for t in item["trigger"] if t.get("id") == "hard_cap")
    assert cap == {
        "trigger": "time",
        "at": "input_datetime.trip_guest_visit_deadline",
        "id": "hard_cap",
    }
    assert trips["input_datetime"]["trip_guest_visit_deadline"] == {
        "name": "Trip Guest Visit Deadline",
        "has_date": True,
        "has_time": True,
    }
    text = yaml.dump(item["action"])
    assert "7200" in text
    assert "deadline_timestamp" in text


def test_open_house_initializes_deadline_before_visit_flag(trips: dict) -> None:
    item = _automation(trips, "trip_guest_door_unlock_open_house")
    triggers = item["trigger"]
    assert any(
        trigger.get("event_type") == "trip_guest_visit_open_house_requested"
        for trigger in triggers
    )
    initialize_visit = item["action"][1]["then"][0]["then"]
    assert initialize_visit[0]["target"]["entity_id"] == (
        "input_datetime.trip_guest_visit_deadline"
    )
    assert initialize_visit[1]["target"]["entity_id"] == (
        "input_boolean.trip_guest_visit_active"
    )
    text = yaml.dump(initialize_visit)
    assert "timedelta(hours=4)" in text


def test_garage_credential_uses_context_motor_and_button(trips: dict) -> None:
    item = _automation(trips, "trip_garage_credentialed_open_starts_visit")
    assert item["trigger"][0]["to"] == "opening"
    text = " ".join(yaml.dump(item, width=10_000).split())
    assert "context.parent_id is none" in text
    assert "context.user_id is none" in text
    assert "binary_sensor.ratgdov25i_1bbf11_motor" in text
    assert "binary_sensor.ratgdov25i_1bbf11_button" in text
    assert "script.trip_guest_visit_start" in text


def test_old_garage_prompt_defers_to_active_visit_and_drops_dead_button(trips: dict) -> None:
    item = _automation(trips, "garage_opened_on_a_trip")
    text = yaml.dump(item)
    assert "input_boolean.trip_guest_visit_active" in text
    assert "IGNORE_GARAGE" not in text
    assert "CLOSE_GARAGE" in text


def test_early_end_never_in_first_twenty_minutes(trips: dict) -> None:
    item = _automation(trips, "trip_guest_visit_early_end")
    assert "> 1200" in yaml.dump(item["condition"])


def test_stale_disarm_rearms_through_arm_alarm(trips: dict) -> None:
    item = _automation(trips, "trip_stale_disarm_rearm")
    text = yaml.dump(item)
    assert "automation.arm_alarm" in text
    assert "minutes: 30" in text
    states = {
        c["entity_id"]: c["state"]
        for c in item["condition"]
        if c["condition"] == "state"
    }
    assert states["input_boolean.trip_guest_visit_active"] == "off"


def test_egress_trigger_is_per_contact_not_aggregate_edge(alerts: dict) -> None:
    item = _automation(alerts, "motion_detected_on_trip")
    entities = [t["entity_id"] for t in item["trigger"]]
    assert "sensor.open_egress_points" in entities
    assert "binary_sensor.any_egress_open" not in entities
    assert "is_number" in yaml.dump(item["condition"])


def test_triggered_response_has_grace_timeline(alerts: dict) -> None:
    item = _automation(alerts, "alarm_triggered_response")
    text = yaml.dump(item["action"])
    assert "00:10:00" in text
    assert "00:05:00" in text
    assert "interruption-level: critical" in _text(ALERTS_PATH)
    assert "input_boolean.trip_guest_visit_active" in text
    assert "script.alarm_strobe_until_resolved" in text
    assert "input_boolean.trip" in text
    assert "Ordinary away mode keeps the immediate alarm response" in text
    # No more immediate whole-house flash loop in the automation itself.
    assert "script.flash_lights" not in text


def test_strobe_stops_on_disarm_or_visit_and_is_scoped(alerts: dict) -> None:
    sequence = alerts["script"]["alarm_strobe_until_resolved"]["sequence"]
    loop = sequence[0]["repeat"]
    text = yaml.dump(loop)
    assert "disarmed" in text
    assert "input_boolean.trip_guest_visit_active" in text
    assert "script.flash_entry_lights" in text
    assert "script.flash_lights" not in text

    flash = alerts["script"]["flash_entry_lights"]["sequence"]
    targets = flash[0]["target"]["entity_id"]
    assert "all" not in targets
    assert "light.hall_main_foyer_1" in targets
