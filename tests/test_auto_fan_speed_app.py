from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = (
    ROOT
    / "appdaemon"
    / "apps"
    / "ad-autofanspeed"
    / "apps"
    / "auto_fan_speed"
    / "auto_fan_speed.py"
)


def _load_auto_fan_module():
    hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")

    class Hass:
        pass

    hassapi.Hass = Hass
    sys.modules.setdefault("appdaemon", types.ModuleType("appdaemon"))
    sys.modules.setdefault("appdaemon.plugins", types.ModuleType("appdaemon.plugins"))
    sys.modules.setdefault("appdaemon.plugins.hass", types.ModuleType("appdaemon.plugins.hass"))
    sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

    spec = importlib.util.spec_from_file_location("auto_fan_speed_test_module", APP_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _app_instance():
    module = _load_auto_fan_module()
    app = module.AutoFanSpeed.__new__(module.AutoFanSpeed)
    app.start = None
    app.end = None
    app.fan = "fan.owner_suite"
    app.is_time_okay = Mock(return_value=True)
    app.get_target_fan_speed = Mock(return_value=50)
    app.call_service = Mock()
    app.debug_log = Mock()
    return app


def test_temperature_change_skips_unavailable_temperature_state() -> None:
    app = _app_instance()

    app.temperature_change(
        "sensor.owner_suite_tph_temperature",
        "state",
        "70.952",
        "unavailable",
        {},
    )

    app.call_service.assert_not_called()
    app.get_target_fan_speed.assert_not_called()
    app.debug_log.assert_called_once_with(
        "AUTO FAN SPEED: skipped non-numeric temperature state 'unavailable'"
    )


def test_temperature_change_sets_fan_speed_for_numeric_temperature_state() -> None:
    app = _app_instance()

    app.temperature_change(
        "sensor.owner_suite_tph_temperature",
        "state",
        "68.0",
        "70.5",
        {},
    )

    app.get_target_fan_speed.assert_called_once_with(70.5)
    app.call_service.assert_called_once_with(
        "fan/set_percentage",
        entity_id="fan.owner_suite",
        percentage=50,
    )
