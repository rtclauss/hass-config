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
            # Cheap planar approximation in meters so distance reflects the
            # actual coordinates (the reference point for the update gate matters).
            return (((self.lat - other.lat) ** 2 + (self.lon - other.lon) ** 2) ** 0.5) * 111_000

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
    app._last_accepted_pos = {}
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


def _make_location_update_app(monkeypatch, baselines=None):
    """An app wired for location_update: away, tracker window open, run_update mocked.

    `baselines` seeds `_last_accepted_pos` ({source_entity_id: (lat, lon)}).
    """
    from datetime import datetime, timezone
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.bayesian = "binary_sensor.bayesian_zeke_home"
    app.minimum_update_window = 5
    app.minimum_update_distance = 20
    app.gps_accuracy_tolerance = 200
    app.error = Mock()
    app.log = Mock()
    app.run_update = Mock(return_value=True)  # published, unless a test overrides
    app._last_accepted_pos = dict(baselines or {})
    # Old published timestamp so the window check passes (fresh_restart=False).
    app.convert_utc = Mock(return_value=datetime(2020, 1, 1, tzinfo=timezone.utc))

    def fake_get_state(entity, attribute=None):
        if entity == app.bayesian:
            return {"state": "off", "attributes": {"probability": 0.1}}
        if entity.startswith("device_tracker."):
            # Fused tracker: only needs gps_updated so the window check passes.
            return {"attributes": {"latitude": 44.5, "longitude": -93.5,
                                   "gps_updated": "2020-01-01T00:00:00+00:00"}}
        return {"attributes": {}}

    app.get_state = Mock(side_effect=fake_get_state)
    return app


def test_location_update_accumulates_against_source_baseline(monkeypatch) -> None:
    """Sub-threshold consecutive deltas still accumulate against the source's OWN
    baseline, so walking-pace reports aren't discarded forever."""
    app = _make_location_update_app(monkeypatch, baselines={"device_tracker.wethop": (44.0, -93.0)})
    # ~11 m between the source's last two reports, but ~211 m from its baseline.
    old = {"attributes": {"latitude": 44.0018, "longitude": -93.0, "gps_accuracy": 10}}
    new = {"attributes": {"latitude": 44.0019, "longitude": -93.0, "gps_accuracy": 10}}

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_called_once()
    assert app._last_accepted_pos["device_tracker.wethop"] == (44.0019, -93.0)  # baseline reset


def test_location_update_skips_near_own_baseline_no_ping_pong(monkeypatch) -> None:
    """A near-stationary source is skipped even if its old->new delta is large, and
    a *different* source's position is irrelevant -- so phone+vehicle can't ping-pong."""
    app = _make_location_update_app(monkeypatch, baselines={
        "device_tracker.nigori_location_tracker": (44.0, -93.0),   # Tesla parked
        "device_tracker.wethop": (44.5, -93.5),                    # phone far away
    })
    # Tesla refresh ~11 m from its OWN baseline (the big old->new jump is a red herring).
    old = {"attributes": {"latitude": 43.99, "longitude": -93.0, "gps_accuracy": 10}}
    new = {"attributes": {"latitude": 44.0001, "longitude": -93.0, "gps_accuracy": 10}}

    app.location_update(entity="device_tracker.nigori_location_tracker", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_not_called()


def test_location_update_first_sighting_unchanged_seeds_without_publishing(monkeypatch) -> None:
    """AppDaemon-only restart (fused entity retained, baselines empty): a source's
    first report with UNCHANGED coords seeds the baseline but must NOT publish --
    otherwise a parked vehicle's refresh could yank the fused location off the phone."""
    app = _make_location_update_app(monkeypatch, baselines={})
    old = {"attributes": {"latitude": 45.0, "longitude": -94.0, "gps_accuracy": 10}}
    new = {"attributes": {"latitude": 45.0, "longitude": -94.0, "gps_accuracy": 10}}  # unchanged

    app.location_update(entity="device_tracker.nigori_location_tracker", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_not_called()
    assert app._last_accepted_pos["device_tracker.nigori_location_tracker"] == (45.0, -94.0)


def test_location_update_first_sighting_with_movement_publishes(monkeypatch) -> None:
    """A source's first post-restart report that actually moved is published."""
    app = _make_location_update_app(monkeypatch, baselines={})
    old = {"attributes": {"latitude": 44.0, "longitude": -93.0, "gps_accuracy": 10}}
    new = {"attributes": {"latitude": 44.01, "longitude": -93.0, "gps_accuracy": 10}}  # ~1.1 km

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_called_once()
    assert app._last_accepted_pos["device_tracker.wethop"] == (44.01, -93.0)


def test_location_update_first_sighting_submove_anchors_at_previous_report(monkeypatch) -> None:
    """A first-sighting sub-threshold move seeds the baseline at the PREVIOUS report
    (not `new`), so the already-traveled segment still counts toward accumulation."""
    app = _make_location_update_app(monkeypatch, baselines={})
    old = {"attributes": {"latitude": 44.0, "longitude": -93.0, "gps_accuracy": 10}}       # P0
    new = {"attributes": {"latitude": 44.00014, "longitude": -93.0, "gps_accuracy": 10}}   # ~15 m

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_not_called()
    # Baseline anchored at P0 (old), not at `new`, so the 15 m already counts.
    assert app._last_accepted_pos["device_tracker.wethop"] == (44.0, -93.0)


def test_location_update_baseline_not_advanced_when_run_update_rejects(monkeypatch) -> None:
    """If run_update rejects the report (e.g. a false-positive 'home'), the source
    baseline must NOT advance -- otherwise a corrective callback looks stationary and
    gets skipped, leaving the fused tracker stale."""
    app = _make_location_update_app(monkeypatch, baselines={"device_tracker.wethop": (44.0, -93.0)})
    app.run_update = Mock(return_value=False)  # simulate rejection
    old = {"attributes": {"latitude": 44.0, "longitude": -93.0, "gps_accuracy": 10}}
    new = {"attributes": {"latitude": 44.01, "longitude": -93.0, "gps_accuracy": 10}}  # moved -> accept path

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_called_once()
    assert app._last_accepted_pos["device_tracker.wethop"] == (44.0, -93.0)  # unchanged


def test_run_update_false_positive_home_returns_false(monkeypatch) -> None:
    """A source flashing 'home' while the bayesian sensor is away is rejected:
    run_update publishes nothing and returns False."""
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.error = Mock()
    app.log = Mock()
    app.tracker_friendly_name = "Zeke"
    app.get_state = Mock(return_value=HOME)
    app.set_state = Mock()

    bayesian_state = {"state": "off", "attributes": {"probability": 0.1, "probability_threshold": 0.8}}
    sensor_state = {
        "entity_id": "device_tracker.wethop",
        "state": "home",  # source flashing home...
        # ...with an extra attr so the away branch is entered (keys != lat/lon/acc)
        "attributes": {"latitude": 44.0, "longitude": -93.0, "gps_accuracy": 10, "battery_level": 90},
    }

    result = app.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)

    assert result is False
    app.set_state.assert_not_called()


def _make_zone_aware_location_app(monkeypatch, baselines):
    """location_update app whose get_state also serves zones (single zone.home,
    radius 100 m at 44.0,-93.0). Bayesian is 'off' (away). `baselines` seeds
    `_last_accepted_pos`. The zone bypass compares each source's OWN baseline zone
    to its new zone -- the fused entity's published state is deliberately irrelevant.
    """
    from datetime import datetime, timezone
    module = _load_tracker_module(monkeypatch)
    app = module.BayesianDeviceTracker.__new__(module.BayesianDeviceTracker)
    app.bayesian_device_tracker_id = "bayesian_zeke_home"
    app.bayesian = "binary_sensor.bayesian_zeke_home"
    app.minimum_update_window = 5
    app.minimum_update_distance = 20
    app.gps_accuracy_tolerance = 200
    app.error = Mock()
    app.log = Mock()
    app.run_update = Mock(return_value=True)
    app._last_accepted_pos = dict(baselines)
    app.convert_utc = Mock(return_value=datetime(2020, 1, 1, tzinfo=timezone.utc))
    zones = {"zone.home": {"attributes": {"latitude": 44.0, "longitude": -93.0, "radius": 100}}}

    def fake_get_state(entity, attribute=None):
        if entity == app.bayesian:
            return {"state": "off", "attributes": {"probability": 0.1}}
        if entity == "zone" and attribute == "all":
            raise ValueError("Querying a specific attribute is only possible for a single entity")
        if entity == "zone":
            return {z: "1" for z in zones}
        if entity in zones:
            return zones[entity]
        if entity.startswith("device_tracker."):
            # Fused entity: only gps_updated matters (for the window check). Its
            # published state is intentionally a DIFFERENT zone to prove the bypass
            # compares against the source baseline, not this.
            return {"state": "Rochester",
                    "attributes": {"latitude": 44.0, "longitude": -93.0,
                                   "gps_updated": "2020-01-01T00:00:00+00:00"}}
        return {"attributes": {}}

    app.get_state = Mock(side_effect=fake_get_state)
    return app


def test_location_update_publishes_zone_change_within_distance_gate(monkeypatch) -> None:
    """A sub-threshold move that crosses a zone boundary (away) must still publish."""
    # baseline ~89 m from home center (inside r=100); new ~105 m (outside) -> zone change,
    # but the two are only ~16 m apart, i.e. under the 20 m gate.
    app = _make_zone_aware_location_app(monkeypatch, baselines={"device_tracker.wethop": (44.00080, -93.0)})
    old = {"attributes": {"latitude": 44.00080, "longitude": -93.0, "gps_accuracy": 5}}
    new = {"attributes": {"latitude": 44.00095, "longitude": -93.0, "gps_accuracy": 5}}

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_called_once()  # baseline zone home -> new zone not_home, despite <20 m


def test_location_update_stationary_source_in_other_zone_no_ping_pong(monkeypatch) -> None:
    """A stationary source whose baseline zone differs from the fused entity's zone
    must NOT publish -- the bypass compares against the source's own baseline zone,
    not the global fused zone (which would ping-pong)."""
    # Source baseline is OUTSIDE home (not_home); the fused entity currently reads
    # "Rochester". A refresh ~5 m away is still not_home -> no per-source zone change.
    app = _make_zone_aware_location_app(monkeypatch, baselines={"device_tracker.wethop": (45.0, -94.0)})
    old = {"attributes": {"latitude": 45.0, "longitude": -94.0, "gps_accuracy": 5}}
    new = {"attributes": {"latitude": 45.00004, "longitude": -94.0, "gps_accuracy": 5}}  # ~4 m

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_not_called()


def test_location_update_suppresses_jitter_when_zone_unchanged(monkeypatch) -> None:
    """A sub-threshold move that stays in the same zone is still suppressed."""
    app = _make_zone_aware_location_app(monkeypatch, baselines={"device_tracker.wethop": (44.00080, -93.0)})
    old = {"attributes": {"latitude": 44.00080, "longitude": -93.0, "gps_accuracy": 5}}
    new = {"attributes": {"latitude": 44.00085, "longitude": -93.0, "gps_accuracy": 5}}  # still inside home

    app.location_update(entity="device_tracker.wethop", attribute="all", old=old, new=new, kwargs={})

    app.run_update.assert_not_called()
