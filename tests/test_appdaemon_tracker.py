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

    # Stub pygeodesy modules used at import time.
    pygeodesy = types.ModuleType("pygeodesy")
    for name in ("ellipsoidalNvector", "ellipsoidalKarney"):
        setattr(pygeodesy, name, types.SimpleNamespace(LatLon=Mock()))
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
    app.get_state = Mock(return_value=zones)
    app.set_state = Mock()
    app.error = Mock()
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
