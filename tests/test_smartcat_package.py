"""Smart Cat notifications: push only for a new kind of change, clear silently."""

from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "smartcat.yaml"
DASHBOARD = ROOT / "lovelace" / "dashboards" / "cats.yaml"


def _config():
    return yaml.safe_load(PACKAGE.read_text())


def _automation(automation_id):
    return next(a for a in _config()["automation"] if a["id"] == automation_id)


def _render(template, **context):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(template).render(**context).strip()


def _state(state, kinds=None, messages=None):
    return {
        "state": state,
        "attributes": {"kinds": kinds or [], "messages": messages or []},
    }


def _attention_branches():
    automation = _automation("smartcat_cat_needs_attention")
    choose = automation["action"][1]["choose"]
    clear, push = choose
    return automation, clear, push


@pytest.mark.parametrize(
    "previous,current,expected",
    [
        # A new problem appears.
        (_state("off"), _state("on", ["frequency_high"]), True),
        # A second, different kind joins an existing one.
        (_state("on", ["weight_loss"]), _state("on", ["weight_loss", "long_visit"]), True),
        # Kind replaced by another kind.
        (_state("on", ["frequency_high"]), _state("on", ["no_recent_visits"]), True),
        # Same kinds, numbers/messages drifted: no re-alert.
        (_state("on", ["weight_loss"], ["down 5%"]), _state("on", ["weight_loss"], ["down 6%"]), False),
        # Reordering is not new.
        (_state("on", ["a", "b"]), _state("on", ["b", "a"]), False),
        # One of two kinds resolved.
        (_state("on", ["a", "b"]), _state("on", ["a"]), False),
        # Back to normal.
        (_state("on", ["a"]), _state("off"), False),
    ],
)
def test_push_only_for_new_kinds(previous, current, expected):
    _, _, push = _attention_branches()
    template = push["conditions"][0]["value_template"]
    result = _render(template, trigger={"from_state": previous, "to_state": current})
    assert result == str(expected)


@pytest.mark.parametrize(
    "previous,current,expected",
    [
        (None, _state("on", ["frequency_high"]), False),
        (_state("unavailable"), _state("on", ["frequency_high"]), False),
        (_state("unknown"), _state("on", ["frequency_high"]), False),
        (_state("on", ["frequency_high"]), _state("unavailable"), False),
        (_state("off"), _state("on", ["frequency_high"]), True),
    ],
)
def test_startup_and_reload_do_not_replay(previous, current, expected):
    automation, _, _ = _attention_branches()
    template = automation["condition"][0]["value_template"]
    assert _render(template, trigger={"from_state": previous, "to_state": current}) == str(expected)


def test_recovery_clears_the_same_tag_silently():
    automation, clear, push = _attention_branches()
    assert automation["trigger"] == [
        {
            "trigger": "state",
            "entity_id": ["binary_sensor.splashy_needs_attention"],
            "attribute": "kinds",
        }
    ]
    recover = _render(
        clear["conditions"][0]["value_template"],
        trigger={"from_state": _state("on", ["a"]), "to_state": _state("off")},
    )
    assert recover == "True"
    (dismiss,) = clear["sequence"]
    assert dismiss["data"]["message"] == "clear_notification"
    (notify,) = push["sequence"]
    assert dismiss["data"]["data"]["tag"] == notify["data"]["data"]["tag"] == "{{ tag }}"

    variables = automation["action"][0]["variables"]
    object_id = _render(
        variables["object_id"],
        trigger={"entity_id": "binary_sensor.splashy_needs_attention"},
    )
    assert object_id == "splashy"
    assert _render(variables["tag"], object_id=object_id) == "smartcat_attention_splashy"
    (button, weight) = notify["data"]["data"]["actions"]
    trigger = {"from_state": {"entity_id": "binary_sensor.splashy_needs_attention"}}
    assert _render(button["uri"], trigger=trigger) == "/?more-info-entity-id=sensor.splashy_insight"
    assert _render(weight["uri"], trigger=trigger) == "/?more-info-entity-id=sensor.splashy_typical_weight"


def test_new_cat_push_and_silent_clear():
    automation = _automation("smartcat_new_cat_suspected")
    triggers = {t["id"]: t for t in automation["trigger"]}
    assert (triggers["suspected"]["from"], triggers["suspected"]["to"]) == ("off", "on")
    assert (triggers["resolved"]["from"], triggers["resolved"]["to"]) == ("on", "off")
    clear, push = automation["action"][0]["choose"]
    assert clear["conditions"] == [{"condition": "trigger", "id": "resolved"}]
    assert clear["sequence"][0]["data"] == {
        "message": "clear_notification",
        "data": {"tag": "smartcat_new_cat"},
    }
    assert push["conditions"] == [{"condition": "trigger", "id": "suspected"}]
    assert push["sequence"][0]["data"]["data"]["tag"] == "smartcat_new_cat"


def test_dashboard_is_registered_and_uses_smartcat_entities():
    configuration = (ROOT / "configuration.yaml").read_text()
    assert "filename: lovelace/dashboards/cats.yaml" in configuration
    dashboard = yaml.safe_load(DASHBOARD.read_text())
    text = DASHBOARD.read_text()
    assert dashboard["views"][0]["path"] == "cats"
    for entity in (
        "sensor.splashy_insight",
        "binary_sensor.splashy_needs_attention",
        "sensor.main_level_waste_drawer_full_forecast",
        "sensor.main_level_litter_refill_forecast",
        "binary_sensor.smart_cat_new_cat_suspected",
        "smartcat:splashy_visits",
    ):
        assert entity in text


def test_dashboard_avoids_whisker_pet_sensor_ids():
    # The core Whisker integration owns sensor.<pet>_weight and
    # sensor.<pet>_visits_today; Smart Cat's own sensors are named so they
    # never collide (and get a _2 suffix) with those.
    text = DASHBOARD.read_text() + PACKAGE.read_text()
    assert "sensor.splashy_weight\n" not in text
    assert "sensor.splashy_visits_today" not in text
    assert "sensor.splashy_typical_weight" in text
    assert "sensor.splashy_daily_visits" in text
