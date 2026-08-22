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
    # Default to "on schedule" (preset_mode present in preset_modes) so
    # existing callers that don't care about hold-detection keep exercising
    # the normal preemption path; pass preset_mode/preset_modes explicitly
    # to test the hold-skip behavior itself.
    attrs = {"preset_mode": "Home Workday", "preset_modes": ["Home Workday"], **attrs}
    app = module.ThermalPreemptor.__new__(module.ThermalPreemptor)
    app.climate_entity = "climate.my_ecobee"
    app.enable_switch = "input_boolean.thermal_preemptor_enabled"
    app.margin_number = "input_number.thermal_preemptor_comfort_margin"
    app.window_gate = "binary_sensor.any_window_open"
    app.rate_sensor = "sensor.ecobee_modeled_rate_deg_per_min"
    app.outside_temp_sensor = "sensor.canonical_outside_temperature"
    app.min_heat_cool_delta = module.MIN_HEAT_COOL_DELTA_F
    app.hold_active_switch = "input_boolean.thermal_preemptor_hold_active"
    app.hold_deadline_datetime = "input_datetime.thermal_preemptor_revert_at"
    app.hold_reason_text = "input_text.thermal_preemptor_hold_reason"
    app.hold_gate = "input_boolean.thermal_preemptor_hold_gate"
    app.active_hold = None
    app.call_service = Mock()
    app.run_in = Mock(return_value="handle")
    app.cancel_timer = Mock()
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
        if entity_id == app.hold_gate:
            return "off"
        if entity_id == app.margin_number:
            return margin
        if entity_id == app.rate_sensor:
            return 0.02
        if entity_id.startswith("sensor.room_temp_prediction_"):
            room = entity_id.rsplit("room_temp_prediction_", 1)[1]
            return predictions.get(room)
        # No persisted hold by default.
        if entity_id == app.hold_active_switch:
            return "off"
        return None

    app.get_state = Mock(side_effect=get_state)
    return app


def _reconcile_app(active, deadline_ts, reason="owner_suite"):
    """A bare app wired only for _reconcile_hold_on_start.

    _reconcile_hold_on_start reads the current time itself, so tests pass a
    deadline relative to real now (well outside any scheduling jitter).
    """
    app = module.ThermalPreemptor.__new__(module.ThermalPreemptor)
    app.climate_entity = "climate.my_ecobee"
    app.hold_active_switch = "input_boolean.thermal_preemptor_hold_active"
    app.hold_deadline_datetime = "input_datetime.thermal_preemptor_revert_at"
    app.hold_reason_text = "input_text.thermal_preemptor_hold_reason"
    app.active_hold = None
    app.call_service = Mock()
    app.run_in = Mock(return_value="handle")
    app.log = Mock()

    def get_state(entity_id, attribute=None):
        if entity_id == app.hold_active_switch:
            return "on" if active else "off"
        if entity_id == app.hold_deadline_datetime and attribute == "timestamp":
            return deadline_ts
        if entity_id == app.hold_reason_text:
            return reason
        return None

    app.get_state = Mock(side_effect=get_state)
    return app


def _now_ts() -> float:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).timestamp()


def _service_calls(app):
    return [call.args[0] for call in app.call_service.call_args_list]


def _set_temperature_call(app):
    # Persisting the hold adds later call_service calls, so find the
    # climate/set_temperature one explicitly rather than reading the last call.
    for call in app.call_service.call_args_list:
        if call.args and call.args[0] == "climate/set_temperature":
            return call
    return None


def _sent_range(app):
    call = _set_temperature_call(app)
    assert call is not None, "expected a set_temperature call"
    return call.kwargs["target_temp_low"], call.kwargs["target_temp_high"]


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

    call = _set_temperature_call(app)
    assert call is not None
    assert call.kwargs["temperature"] == 69.0


# --------------------------------------------------------------------------
# Pre-existing hold preservation (Codex P2 on #864)
# --------------------------------------------------------------------------


def test_skips_preemption_when_a_pre_existing_hold_is_already_active() -> None:
    # If the thermostat is already under a manual/app hold when the control
    # loop runs, starting our own hold and later resuming the schedule on
    # revert would silently discard whatever the user set. preset_mode
    # outside preset_modes indicates a hold is already active.
    app = _app(
        "cool",
        {
            "temperature": 72.0,
            "preset_mode": "temp",
            "preset_modes": ["Home Workday", "sleep", "away"],
        },
        {"owner_suite": 75.0},
    )
    app._control_loop(None)

    assert not app.call_service.called
    assert app.active_hold is None


def test_preempts_normally_when_preset_mode_matches_the_active_schedule() -> None:
    app = _app(
        "cool",
        {
            "temperature": 72.0,
            "preset_mode": "sleep",
            "preset_modes": ["Home Workday", "sleep", "away"],
        },
        {"owner_suite": 75.0},
    )
    app._control_loop(None)

    call = _set_temperature_call(app)
    assert call is not None
    assert app.active_hold is not None


# --------------------------------------------------------------------------
# Hold persistence and restart reconciliation (orphaned-override / ratchet bug)
# --------------------------------------------------------------------------


def test_applying_a_hold_persists_it_to_helpers() -> None:
    # A restart mid-hold must be recoverable, so the setpoint override is
    # mirrored into helpers whenever it is armed.
    app = _app("cool", {"temperature": 72.0}, {"owner_suite": 75.0})
    app._control_loop(None)

    calls = _service_calls(app)
    assert "input_datetime/set_datetime" in calls
    assert "input_text/set_value" in calls
    assert "input_boolean/turn_on" in calls
    # Active flag set last, after the deadline is written.
    assert calls.index("input_boolean/turn_on") > calls.index("input_datetime/set_datetime")
    assert app.active_hold is not None


def test_revert_clears_the_persisted_hold() -> None:
    app = _app("cool", {"temperature": 72.0}, {"owner_suite": 75.0})
    app._revert({"room": "owner_suite"})

    calls = _service_calls(app)
    assert "ecobee/resume_program" in calls
    assert "input_boolean/turn_off" in calls
    assert app.active_hold is None


def test_reconcile_rearms_an_in_flight_hold_after_reload() -> None:
    # Deadline still in the future: re-arm the revert timer and restore the
    # in-memory hold so the re-entry guard blocks a second shift.
    app = _reconcile_app(active=True, deadline_ts=_now_ts() + 600)
    app._reconcile_hold_on_start()

    assert app.run_in.called
    delay = app.run_in.call_args.args[1]
    assert 0 < delay <= 600
    assert app.active_hold is not None
    assert app.active_hold["recovered"] is True
    # It must NOT resume immediately — the hold is still valid.
    assert "ecobee/resume_program" not in _service_calls(app)


def test_reconcile_resumes_immediately_when_the_deadline_already_passed() -> None:
    # The daemon was down past the revert deadline: resume the schedule now and
    # clear the flag rather than leave the override on the thermostat.
    app = _reconcile_app(active=True, deadline_ts=_now_ts() - 60)
    app._reconcile_hold_on_start()

    calls = _service_calls(app)
    assert "ecobee/resume_program" in calls
    assert "input_boolean/turn_off" in calls
    assert not app.run_in.called
    assert app.active_hold is None


def test_reconcile_resumes_when_the_deadline_is_unreadable() -> None:
    # Active flag set but no usable deadline — fail safe by resuming.
    app = _reconcile_app(active=True, deadline_ts=None)
    app._reconcile_hold_on_start()

    assert "ecobee/resume_program" in _service_calls(app)
    assert app.active_hold is None


def test_reconcile_is_a_noop_when_no_hold_was_persisted() -> None:
    app = _reconcile_app(active=False, deadline_ts=None)
    app._reconcile_hold_on_start()

    assert not app.call_service.called
    assert not app.run_in.called
    assert app.active_hold is None


def test_recovered_hold_blocks_the_control_loop_from_shifting_again() -> None:
    # The whole point of persistence: after a reload the restored hold must make
    # the control loop a no-op, so it cannot read the already-shifted setpoint
    # and ratchet it further. Cooling breach present, but a hold is active.
    app = _app("cool", {"temperature": 69.0}, {"owner_suite": 75.0})
    app.active_hold = {"reason": "owner_suite", "recovered": True}

    app._control_loop(None)

    assert _set_temperature_call(app) is None, "shifted the setpoint while a hold was active"


# --------------------------------------------------------------------------
# Stale timer cancellation on early revert (Codex P2 on #864)
# --------------------------------------------------------------------------


def test_early_revert_cancels_the_scheduled_timer() -> None:
    # When the kill switch fires an early revert, _revert must cancel the
    # original run_in handle so the stale callback cannot call resume_program
    # a second time and wipe a subsequent hold.
    app = _app("cool", {"temperature": 72.0}, {"owner_suite": 75.0})
    app.active_hold = {"revert_handle": "handle_xyz", "reason": "owner_suite"}

    original = app.get_state.side_effect

    def disabled(entity_id, attribute=None):
        if entity_id == app.enable_switch:
            return "off"
        return original(entity_id, attribute)

    app.get_state = Mock(side_effect=disabled)
    app._control_loop(None)

    app.cancel_timer.assert_called_once_with("handle_xyz")
    assert app.active_hold is None


# --------------------------------------------------------------------------
# External hold gate (Codex P2 on #864)
# --------------------------------------------------------------------------


def test_hold_gate_blocks_preemption_during_named_preset_hold() -> None:
    # house_mode.yaml turns this gate on when it applies a named-preset hold
    # (e.g. guest climate); the preemptor must not start its own override on top.
    app = _app("cool", {"temperature": 72.0}, {"owner_suite": 75.0})

    original = app.get_state.side_effect

    def gate_on(entity_id, attribute=None):
        if entity_id == app.hold_gate:
            return "on"
        return original(entity_id, attribute)

    app.get_state = Mock(side_effect=gate_on)
    app._control_loop(None)

    assert not app.call_service.called
    assert app.active_hold is None


def test_hold_gate_cancels_an_active_preempt_hold_when_turned_on() -> None:
    # If the gate is turned on while preemption is already in flight, the hold
    # must be reverted immediately — same semantics as kill-switch / window gate.
    app = _app("cool", {"temperature": 72.0}, {"owner_suite": 75.0})
    app.active_hold = {"revert_handle": "handle_xyz", "reason": "owner_suite"}

    original = app.get_state.side_effect

    def gate_on(entity_id, attribute=None):
        if entity_id == app.hold_gate:
            return "on"
        return original(entity_id, attribute)

    app.get_state = Mock(side_effect=gate_on)
    app._control_loop(None)

    assert "ecobee/resume_program" in _service_calls(app)
    app.cancel_timer.assert_called_once_with("handle_xyz")
    assert app.active_hold is None
