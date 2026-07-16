"""Tests for ThermalPreemptor's setpoint math.

thermal_preemptor.py does `import hassapi as hass`, so hassapi is stubbed here
rather than installed (same approach as test_auto_fan_speed_app.py).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "appdaemon" / "apps" / "thermal_preemptor.py"


def _load_preemptor_module():
    hassapi = types.ModuleType("hassapi")

    class Hass:
        pass

    hassapi.Hass = Hass
    sys.modules["hassapi"] = hassapi

    spec = importlib.util.spec_from_file_location("thermal_preemptor_test_module", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = _load_preemptor_module()


def _app(mode, attrs, predictions, margin=0.5):
    app = module.ThermalPreemptor.__new__(module.ThermalPreemptor)
    app.climate_entity = "climate.my_ecobee"
    app.enable_switch = "input_boolean.thermal_preemptor_enabled"
    app.margin_number = "input_number.thermal_preemptor_comfort_margin"
    app.window_gate = "binary_sensor.any_window_open"
    app.rate_sensor = "sensor.ecobee_modeled_rate_deg_per_min"
    app.outside_temp_sensor = "sensor.canonical_outside_temperature"
    app.min_heat_cool_delta = module.MIN_HEAT_COOL_DELTA_F
    app.active_hold = None
    app.call_service = Mock()
    app.run_in = Mock(return_value="handle")
    app.log = Mock()

    def get_state(entity_id, attribute=None):
        if entity_id == app.climate_entity and attribute is None:
            return mode
        if entity_id == app.climate_entity:
            return attrs.get(attribute)
        if entity_id == app.enable_switch:
            return "on"
        if entity_id == app.window_gate:
            return "off"
        if entity_id == app.margin_number:
            return margin
        if entity_id == app.rate_sensor:
            return 0.02
        if entity_id.startswith("sensor.room_temp_prediction_"):
            room = entity_id.rsplit("room_temp_prediction_", 1)[1]
            return predictions.get(room)
        return None

    app.get_state = Mock(side_effect=get_state)
    return app


def _sent_range(app):
    assert app.call_service.called, "expected a set_temperature call"
    kwargs = app.call_service.call_args.kwargs
    return kwargs["target_temp_low"], kwargs["target_temp_high"]


def test_heat_cool_precool_never_inverts_the_range() -> None:
    # 68-70 range with a 3F cooling breach: the raw nudge is high=67 against
    # low=68, an inverted range the thermostat rejects.
    app = _app(
        "heat_cool",
        {"target_temp_high": 70.0, "target_temp_low": 68.0},
        {"owner_suite": 73.0},
    )
    app._control_loop(None)

    if app.call_service.called:
        low, high = _sent_range(app)
        assert high > low, f"sent an inverted range: high={high} low={low}"
        assert high - low >= app.min_heat_cool_delta


def test_heat_cool_precool_skips_when_no_headroom_remains() -> None:
    # A 68-70 band cannot be precooled at all without crowding the heat bound,
    # so the app should do nothing rather than send a crowded/inverted range.
    app = _app(
        "heat_cool",
        {"target_temp_high": 70.0, "target_temp_low": 68.0},
        {"owner_suite": 73.0},
    )
    app._control_loop(None)

    assert not app.call_service.called
    assert app.run_in.call_count == 0
    assert app.active_hold is None


def test_heat_cool_precool_still_nudges_a_wide_range() -> None:
    # 60-78 leaves plenty of room: a 3F shift keeps the delta well above minimum.
    app = _app(
        "heat_cool",
        {"target_temp_high": 78.0, "target_temp_low": 60.0},
        {"owner_suite": 81.0},
    )
    app._control_loop(None)

    low, high = _sent_range(app)
    assert (low, high) == (60.0, 75.0)
    assert high - low >= app.min_heat_cool_delta


def test_heat_cool_preheat_never_crosses_the_cool_bound() -> None:
    app = _app(
        "heat_cool",
        {"target_temp_high": 70.0, "target_temp_low": 68.0},
        {"owner_suite": 65.0},
    )
    app._control_loop(None)

    if app.call_service.called:
        low, high = _sent_range(app)
        assert high > low
        assert high - low >= app.min_heat_cool_delta


def test_single_setpoint_cool_mode_is_unaffected_by_the_range_clamp() -> None:
    app = _app("cool", {"temperature": 72.0}, {"owner_suite": 75.0})
    app._control_loop(None)

    assert app.call_service.called
    assert app.call_service.call_args.kwargs["temperature"] == 69.0
