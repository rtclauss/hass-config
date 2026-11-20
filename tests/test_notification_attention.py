"""The owner's new route must preserve every existing recipient and action."""
from copy import deepcopy
import pytest
from scripts.notification_attention import add_recipient_attention

OWNER = "notify.mobile_app_example_owner"


def _add(config, **overrides):
    arguments = {"recipient_service": OWNER,
        "existing_recipients": {"notify.mobile_app_example_family"},
        "title": "Check appliance power", "message": "Power status is off. Check the appliance.",
        "tag": "example-home-appliance-power",
        "destinations": [("Power status", "binary_sensor.example_power"), ("Power reading", "sensor.example_power")]}
    arguments.update(overrides)
    return add_recipient_attention(config, **arguments)


@pytest.mark.parametrize("key,service_key", [("actions", "action"), ("action", "service")])
def test_only_owner_delivery_is_added_and_original_behavior_is_preserved(key, service_key):
    config = {"id": "example_appliance", "mode": "single",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.example_power", "to": "off"}],
        key: [{service_key: "notify.all", "data": {"message": "Original family message", "data": {"tag": "family-alert"}}},
            {"action": "logbook.log", "data": {"name": "Existing evidence", "message": "Recorded"}}]}
    original = deepcopy(config)
    result = _add(config)
    assert config == original
    assert {k:v for k,v in result.items() if k != key} == {k:v for k,v in original.items() if k != key}
    assert result[key][1:] == original[key]
    new = result[key][0]
    assert new["action"] == OWNER
    assert new["continue_on_error"] is True
    metadata = new["data"]["data"]
    assert metadata["url"] == metadata["clickAction"] == "/?more-info-entity-id=binary_sensor.example_power"
    assert metadata["tag"] == "example-home-appliance-power"
    assert [button["action"] for button in metadata["actions"]] == ["URI", "URI"]
    assert metadata["actions"][1]["uri"] == "/?more-info-entity-id=sensor.example_power"


@pytest.mark.parametrize("overrides", [
    {"recipient_service": "notify.all"}, {"existing_recipients": {OWNER}},
    {"destinations": []}, {"destinations": [("Status", "sensor.example")] * 4},
    {"destinations": [("Status", "https://example.invalid")]}, {"destinations": [("", "sensor.example")]},
    {"title": ""}, {"message": ""}, {"tag": ""}])
def test_invalid_or_duplicate_routes_are_rejected_without_mutation(overrides):
    config = {"actions": [{"action": "notify.all", "data": {"message": "Alert"}}]}
    original = deepcopy(config)
    with pytest.raises(ValueError):
        _add(config, **overrides)
    assert config == original


@pytest.mark.parametrize("message", ["clear_notification", "request_location_update", "command_activity", None])
def test_mobile_commands_are_never_reissued_as_attention_alerts(message):
    with pytest.raises(ValueError):
        _add({"actions": [{"action": "notify.all", "data": {"message": message}}]})


@pytest.mark.parametrize("actions", [None, [], [{"action": "notify.all"}] * 2])
def test_unknown_or_ambiguous_structure_fails_closed(actions):
    with pytest.raises(ValueError):
        _add({"actions": actions})
