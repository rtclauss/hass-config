from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "appdaemon" / "apps" / "tracker.py"


def _load_tracker_module(monkeypatch):
    """Load tracker.py with its heavy geo dependencies stubbed out."""
    hassapi = types.ModuleType("hassapi")

    class Hass:
        pass

    hassapi.Hass = Hass
    monkeypatch.setitem(sys.modules, "hassapi", hassapi)

    # Stub geopy.distance.great_circle -> object exposing `.meters`.
    geopy = types.ModuleType("geopy")
    geopy_distance = types.ModuleType("geopy.distance")

    class _GreatCircle:
        def __init__(self, a, b):
            # Cheap planar approximation is good enough for unit tests: scale
            # degrees to meters so the resolver's radius comparisons are stable.
            lat1, lon1 = a
            lat2, lon2 = b
            self.meters = (((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2) ** 0.5) * 111_000

    geopy_distance.great_circle = _GreatCircle
    geopy.distance = geopy_distance
    monkeypatch.setitem(sys.modules, "geopy", geopy)
    monkeypatch.setitem(sys.modules, "geopy.distance", geopy_distance)

    # Stub pygeodesy modules used at import time. LatLon exposes just enough of
    # the geodesic API for location_update's distance math to run.
    class _LatLon:
        def __init__(self, lat=0.0, lon=0.0):
            self.lat = lat
            self.lon = lon

        def distanceTo(self, other):
            return 1000.0

        def intermediateTo(self, other, ratio):
            return _LatLon(other.lat, other.lon)

    pygeodesy = types.ModuleType("pygeodesy")
    for name in ("ellipsoidalNvector", "ellipsoidalKarney"):
        setattr(pygeodesy, name, types.SimpleNamespace(LatLon=_LatLon))
        monkeypatch.setitem(sys.modules, f"pygeodesy.{name}", getattr(pygeodesy, name))
    monkeypatch.setitem(sys.modules, "pygeodesy", pygeodesy)

    spec = importlib.util.spec_from_file_location("tracker_test_module", APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_app(monkeypatch, zones):
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"

    # Mirror the real AppDaemon zone API: get_state("zone") -> {id: state};
    # per-entity get_state("zone.x", attribute="all") -> full dict. Querying
    # attribute="all" across the whole domain is NOT supported (raises), so the
    # app must never rely on it.
    def _fake_get_state(entity=None, attribute=None):
        if entity == "zone" and attribute == "all":
            raise ValueError("Querying a specific attribute is only possible for a single entity")
        if entity == "zone":
            return {zid: "1" for zid in zones}
        if entity in zones:
            return zones[entity]
        return None

    app.get_state = Mock(side_effect=_fake_get_state)
    app.set_state = Mock()
    app.error = Mock()
    app.log = Mock()
    app.tracker_friendly_name = "Zeke"
    return app


HOME = {
    "zone.home": {
        "attributes": {"latitude": 44.0, "longitude": -93.0, "radius": 100},
    },
    "zone.rochester": {
        "attributes": {"latitude": 44.02, "longitude": -92.46, "radius": 20000, "friendly_name": "Rochester"},
    },
}


def test_see_service_no_longer_called_in_source() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    # The deprecated action is invoked as "device_tracker/see" via call_service.
    # It may still appear in docstrings/comments explaining the migration.
    assert "device_tracker/see" not in source
    assert 'call_service("device_tracker' not in source


def test_update_tracker_uses_set_state_not_see(monkeypatch) -> None:
    app = _make_app(monkeypatch, HOME)

    app.update_tracker(latitude=44.0, longitude=-93.0, attributes={"course": 0.0})

    app.set_state.assert_called_once()
    args, kwargs = app.set_state.call_args
    assert args[0] == "device_tracker.bayesian_zeke_home"
    assert kwargs["state"] == "home"
    assert kwargs["attributes"]["latitude"] == 44.0
    assert kwargs["attributes"]["longitude"] == -93.0
    assert kwargs["attributes"]["source_type"] == "gps"
    assert kwargs["attributes"]["course"] == 0.0


def test_resolve_state_home_zone(monkeypatch) -> None:
    app = _make_app(monkeypatch, HOME)
    assert app.resolve_tracker_state(44.0, -93.0) == "home"


def test_resolve_state_named_zone_over_larger_zone(monkeypatch) -> None:
    app = _make_app(monkeypatch, HOME)
    # Inside Rochester but far from the small home zone -> named zone.
    assert app.resolve_tracker_state(44.02, -92.46) == "Rochester"


def test_resolve_state_not_home_when_outside_all_zones(monkeypatch) -> None:
    app = _make_app(monkeypatch, HOME)
    assert app.resolve_tracker_state(40.0, -80.0) == "not_home"


def test_resolve_state_ignores_passive_zones(monkeypatch) -> None:
    zones = {
        "zone.passive_here": {
            "attributes": {"latitude": 44.0, "longitude": -93.0, "radius": 50, "passive": True},
        },
    }
    app = _make_app(monkeypatch, zones)
    assert app.resolve_tracker_state(44.0, -93.0) == "not_home"


def test_resolve_state_none_coordinates(monkeypatch) -> None:
    app = _make_app(monkeypatch, HOME)
    assert app.resolve_tracker_state(None, None) == "not_home"


def test_location_update_survives_missing_tracker_entity(monkeypatch) -> None:
    """A cold start where the tracker entity does not exist yet must not crash.

    get_state() returns None for the tracker, so the gps_updated lookup raises
    TypeError; the app should treat that as a fresh restart and proceed to
    run_update rather than letting the callback error out.
    """
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.bayesian = "binary_sensor.bayesian_zeke_home"
    app.minimum_update_window = 300
    app.minimum_update_distance = 50
    app.gps_accuracy_tolerance = 100
    app.error = Mock()
    app.log = Mock()
    app.run_update = Mock()
    app.convert_utc = Mock()  # real AppDaemon method; present so the None subscript is what raises

    def fake_get_state(entity, attribute=None):
        if entity == app.bayesian:
            return {"state": "off", "attributes": {"probability": 0.1}}
        if entity.startswith("device_tracker."):
            return None  # entity not created yet on cold start
        return {"attributes": {}}

    app.get_state = Mock(side_effect=fake_get_state)

    new = {"attributes": {"latitude": 44.5, "longitude": -92.5, "gps_accuracy": 10}}
    old = {"attributes": {"latitude": 45.0, "longitude": -92.0, "gps_accuracy": 10}}

    # Should not raise despite the missing tracker entity.
    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_called_once()


def test_run_update_survives_missing_tracker_entity(monkeypatch) -> None:
    """run_update must not crash when the tracker entity does not exist yet.

    The away branch re-fetches device_tracker.<id> to blend the previous
    location; on a cold start get_state() returns None, so dereferencing
    dev_tracker_state["attributes"] raises TypeError. It must be handled so the
    update falls back to the new location and update_tracker recreates the
    entity via set_state.
    """
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.error = Mock()
    app.log = Mock()
    app.tracker_friendly_name = "Zeke"

    def fake_get_state(entity, attribute=None):
        if entity == "zone":
            return HOME
        if entity.startswith("device_tracker."):
            return None  # tracker not created yet on cold start
        return {"attributes": {}}

    app.get_state = Mock(side_effect=fake_get_state)
    app.set_state = Mock()

    bayesian_state = {"state": "off", "attributes": {"probability": 0.9, "probability_threshold": 0.5}}
    sensor_state = {
        "entity_id": "device_tracker.wethop",
        "state": "not_home",
        "attributes": {
            "latitude": 44.5,
            "longitude": -92.5,
            "gps_accuracy": 10,
            "speed": 5.0,
            "battery": 80,
        },
    }

    # Should not raise despite the missing tracker entity.
    app.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)

    app.set_state.assert_called_once()
    args, kwargs = app.set_state.call_args
    assert args[0] == "device_tracker.bayesian_zeke_home"
    assert kwargs["attributes"]["source_type"] == "gps"


def test_update_tracker_state_override_bypasses_zone_resolution(monkeypatch) -> None:
    """The bayesian home path forces state='home' even when zone lookup fails.

    Reproduces the production failure: get_state("zone", attribute="all")
    returns None, so resolve_tracker_state would yield 'not_home'. The explicit
    state override must win so the tracker still reports home.
    """
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.tracker_friendly_name = "Zeke"
    app.set_state = Mock()
    app.get_state = Mock(return_value=None)  # every zone lookup fails
    app.log = Mock()
    app.error = Mock()

    app.update_tracker(latitude=44.0, longitude=-93.0,
                       attributes={"course": 0.0}, state="home")

    _, kwargs = app.set_state.call_args
    assert kwargs["state"] == "home"


def test_update_tracker_strips_source_identity_attrs(monkeypatch) -> None:
    """A GPS source's identity attributes must not leak onto the fused tracker."""
    app = _make_app(monkeypatch, HOME)

    app.update_tracker(latitude=44.0, longitude=-93.0, attributes={
        "friendly_name": "Nigori Location tracker",
        "in_zones": ["zone.neighborhood"],
        "last_changed": "2026-08-10T00:00:00",
        "context": {"id": "abc"},
        "home_probability": 1,
    })

    _, kwargs = app.set_state.call_args
    attrs = kwargs["attributes"]
    assert attrs["friendly_name"] == "Zeke"          # stable name, not the source's
    assert "in_zones" not in attrs
    assert "last_changed" not in attrs
    assert "context" not in attrs
    assert attrs["home_probability"] == 1            # legitimate attrs preserved


def test_zone_states_enumerates_per_entity(monkeypatch) -> None:
    """resolve must never call get_state('zone', attribute='all').

    That call raises ValueError in this AppDaemon ("Querying a specific attribute
    is only possible for a single entity"). resolve_tracker_state must enumerate
    the domain and fetch each zone individually so a home point resolves to
    'home'. If it touches the domain+all form, this fake raises and the test fails.
    """
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.log = Mock()

    def fake_get_state(entity=None, attribute=None):
        if entity == "zone" and attribute == "all":
            raise ValueError("Querying a specific attribute is only possible for a single entity")
        if entity == "zone":
            return {"zone.home": "1"}  # domain enumeration
        if entity == "zone.home":
            return {"attributes": {"latitude": 44.0, "longitude": -93.0, "radius": 100}}
        return None

    app.get_state = Mock(side_effect=fake_get_state)

    assert app.resolve_tracker_state(44.0, -93.0) == "home"


def test_resolve_state_not_home_if_zone_query_raises(monkeypatch) -> None:
    """If even get_state('zone') raises, resolve degrades to not_home (no crash)."""
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.log = Mock()

    def fake_get_state(entity=None, attribute=None):
        raise ValueError("boom")

    app.get_state = Mock(side_effect=fake_get_state)

    assert app.resolve_tracker_state(44.0, -93.0) == "not_home"


def test_run_update_away_source_without_speed_still_updates(monkeypatch) -> None:
    """Away update from a source lacking 'speed' (e.g. the iOS phone) must complete.

    The away branch re-copies gps_attributes, dropping the speed=0.0 default set
    at the top of run_update, so a hard attributes['speed'] access raised
    KeyError -- silently swallowed by the outer handler -- and the tracker never
    left 'home'. It must resolve zones and call set_state instead.
    """
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.error = Mock()
    app.log = Mock()
    app.tracker_friendly_name = "Zeke"

    def fake_get_state(entity, attribute=None):
        if entity == "zone":
            return HOME
        if entity.startswith("device_tracker."):
            return {"attributes": {"latitude": 44.0, "longitude": -93.0}}
        return {"attributes": {}}

    app.get_state = Mock(side_effect=fake_get_state)
    app.set_state = Mock()

    bayesian_state = {"state": "off", "attributes": {"probability": 0.9, "probability_threshold": 0.5}}
    sensor_state = {
        "entity_id": "device_tracker.wethop",
        "state": "not_home",
        "attributes": {
            "latitude": 44.5,
            "longitude": -92.5,
            "gps_accuracy": 20,
            "battery_level": 100,
            # NB: no 'speed' key -- the iOS phone tracker omits it
        },
    }

    app.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)

    app.set_state.assert_called_once()
    _, kwargs = app.set_state.call_args
    assert kwargs["state"] == "not_home"  # 44.5,-92.5 is outside the test zones


def test_update_tracker_replaces_attributes(monkeypatch) -> None:
    """set_state must use replace=True so stale attributes cannot persist.

    AppDaemon merges attributes by default, so stripping a key from the outgoing
    dict does not remove it from an entity that already carries it. The fix must
    replace the whole attribute mapping.
    """
    app = _make_app(monkeypatch, HOME)

    app.update_tracker(latitude=44.0, longitude=-93.0, attributes={"course": 0.0}, state="home")

    _, kwargs = app.set_state.call_args
    assert kwargs.get("replace") is True
