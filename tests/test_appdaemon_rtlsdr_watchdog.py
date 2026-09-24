from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "appdaemon" / "apps" / "rtlsdr_watchdog.py"
APPS_YAML_PATH = ROOT / "appdaemon" / "apps" / "apps.yaml"
GITIGNORE_PATH = ROOT / ".gitignore"
SYNC_SCRIPT_PATH = ROOT / "scripts" / "appdaemon_sync.py"


def _load_module(monkeypatch):
    hassapi = types.ModuleType("hassapi")

    class Hass:
        pass

    hassapi.Hass = Hass
    monkeypatch.setitem(sys.modules, "hassapi", hassapi)

    spec = importlib.util.spec_from_file_location("rtlsdr_watchdog_test_module", APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_app(monkeypatch, tmp_path, args=None, now=None):
    module = _load_module(monkeypatch)
    monkeypatch.setattr(module, "STATE_FILE", str(tmp_path / "state.json"))

    app = module.RtlSdrWatchdog.__new__(module.RtlSdrWatchdog)
    app.args = dict(args or {})
    app.log = Mock()
    app.call_service = Mock()
    app.run_in = Mock()
    app.run_every = Mock()
    app.listen_event = Mock()
    app.get_state = Mock(return_value=None)

    fixed_now = now or datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    app._now = Mock(return_value=fixed_now)

    module.RtlSdrWatchdog.initialize(app)
    return module, app


def _set_now(app, when):
    app._now = Mock(return_value=when)


REAL_LOG_SAMPLE = """\
[2026-09-24 09:37:55,057] INFO: rtlamr is ready
[2026-09-24 09:38:00,059] WARNING: rtlamr process died (exit code: 1), attempting restart
[2026-09-24 09:38:00,059] WARNING: rtlamr last output before exit:
  time=2026-09-24T09:37:55.057-05:00 level=INFO msg="CenterFreq: 912600155"
  time=2026-09-24T09:38:00.058-05:00 level=ERROR msg=receiver error="read tcp 127.0.0.1:58338->127.0.0.1:1234: i/o timeout"
[2026-09-24 09:38:00,059] INFO: Starting rtlamr: /usr/bin/stdbuf -oL /usr/bin/rtlamr
"""


# -- log matching -------------------------------------------------------------


def test_usb_fault_pattern_matches_case_insensitively(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    usb, generic = app._match_logs("ERROR: USB_CLAIM_INTERFACE ERROR on device 0")
    assert usb
    assert not generic


def test_ansi_codes_stripped_before_matching(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    text = "\x1b[31mNo supported devices found\x1b[0m"
    usb, _ = app._match_logs(text)
    assert usb


def test_generic_pattern_alone_never_counts_as_usb(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    usb, generic = app._match_logs("Traceback (most recent call last):\nErrno 111 Connection refused")
    assert not usb
    assert generic


def test_death_loop_below_threshold_is_no_hit(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"death_loop_min_count": 5})
    text = "\n".join(["rtlamr process died (exit code: 1), attempting restart"] * 4)
    usb, generic = app._match_logs(text)
    assert not usb
    assert not generic


def test_death_loop_at_threshold_is_usb_hit(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"death_loop_min_count": 5})
    text = "\n".join(["rtlamr process died (exit code: 1), attempting restart"] * 5)
    usb, _ = app._match_logs(text)
    assert usb


def test_real_sample_log_below_threshold_produces_no_hit(monkeypatch, tmp_path):
    # One occurrence, as in the real-world sample - should not trigger on its own.
    module, app = _make_app(monkeypatch, tmp_path, args={"death_loop_min_count": 5})
    usb, generic = app._match_logs(REAL_LOG_SAMPLE)
    assert not usb
    assert not generic


def test_clean_log_has_no_hits(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    usb, generic = app._match_logs("[INFO] rtlamr is ready\n[INFO] publishing reading")
    assert not usb
    assert not generic


# -- freshness / staleness -----------------------------------------------------


def test_newest_of_three_timestamps_wins(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    # Mirrors the live shape: last_seen *state* is stale-looking, but
    # last_updated on both entities is recent.
    values = {
        (app.reading_entity, "last_updated"): "2026-09-24T11:55:00+00:00",
        (app.last_seen_entity, "last_updated"): "2026-09-24T11:50:00+00:00",
        (app.last_seen_entity, None): "2026-09-22T20:15:36+00:00",
    }

    def fake_get_state(entity, attribute=None):
        return values.get((entity, attribute))

    app.get_state = Mock(side_effect=fake_get_state)
    last = app._last_reading_at()
    assert last == datetime(2026, 9, 24, 11, 55, tzinfo=timezone.utc)


def test_unparseable_values_are_skipped(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    app.get_state = Mock(return_value="unavailable")
    assert app._last_reading_at() is None


def test_stale_boundary(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"stale_after_minutes": 60})
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    app._last_reading_at = Mock(return_value=now - timedelta(minutes=59))
    assert app._is_stale(now) is False

    app._last_reading_at = Mock(return_value=now - timedelta(minutes=60))
    assert app._is_stale(now) is True


def test_is_stale_none_when_no_reading(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    app._last_reading_at = Mock(return_value=None)
    assert app._is_stale(datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)) is None


# -- decision logic: AND gate + debounce ---------------------------------------


def _prep_for_check(app, *, stale, logs):
    app._is_stale = Mock(return_value=stale)
    app._fetch_logs = Mock(return_value=logs)
    app._escalate = Mock()
    # Clear the startup-grace / settle windows so check() actually evaluates.
    app.started_at = app._now() - app.startup_grace - timedelta(minutes=1)
    app.state["last_restart_ts"] = None


def test_stale_with_no_log_hit_never_escalates(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    _prep_for_check(app, stale=True, logs="[INFO] rtlamr is ready")
    app.check({})
    app._escalate.assert_not_called()
    assert app.unhealthy_cycles == 0


def test_fresh_with_log_hit_never_escalates(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    _prep_for_check(app, stale=False, logs="No supported devices found")
    app.check({})
    app._escalate.assert_not_called()


def test_single_unhealthy_cycle_does_not_escalate(monkeypatch, tmp_path, args=None):
    module, app = _make_app(monkeypatch, tmp_path, args={"confirm_cycles": 2})
    _prep_for_check(app, stale=True, logs="No supported devices found")
    app.check({})
    app._escalate.assert_not_called()
    assert app.unhealthy_cycles == 1


def test_two_consecutive_unhealthy_cycles_escalates(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"confirm_cycles": 2})
    _prep_for_check(app, stale=True, logs="No supported devices found")
    app.check({})
    app.check({})
    app._escalate.assert_called_once()
    args, kwargs = app._escalate.call_args
    assert kwargs["usb_fault"] is True


def test_clean_cycle_between_hits_resets_counter(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"confirm_cycles": 2})
    _prep_for_check(app, stale=True, logs="No supported devices found")
    app.check({})
    assert app.unhealthy_cycles == 1

    _prep_for_check(app, stale=True, logs="[INFO] rtlamr is ready")
    app.check({})
    assert app.unhealthy_cycles == 0

    _prep_for_check(app, stale=True, logs="No supported devices found")
    app.check({})
    assert app.unhealthy_cycles == 1
    app._escalate.assert_not_called()


def test_unreadable_logs_never_escalate(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"confirm_cycles": 1})
    _prep_for_check(app, stale=True, logs=None)
    app.check({})
    app._escalate.assert_not_called()
    assert app.unhealthy_cycles == 0


def test_missing_sensor_never_escalates(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"confirm_cycles": 1})
    _prep_for_check(app, stale=None, logs="No supported devices found")
    app.check({})
    app._escalate.assert_not_called()


def test_startup_grace_window_suppresses_evaluation(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"startup_grace_minutes": 20})
    app._is_stale = Mock(return_value=True)
    app._fetch_logs = Mock(return_value="No supported devices found")
    app._escalate = Mock()
    app.started_at = app._now()  # just initialized

    app.check({})
    app._is_stale.assert_not_called()
    app._escalate.assert_not_called()


def test_settle_window_after_restart_suppresses_evaluation(monkeypatch, tmp_path):
    module, app = _make_app(
        monkeypatch, tmp_path, args={"restart_settle_minutes": 25, "startup_grace_minutes": 0}
    )
    app.started_at = app._now() - timedelta(hours=1)
    app.state["last_restart_ts"] = app._now().isoformat()
    app._is_stale = Mock(return_value=True)

    app.check({})
    app._is_stale.assert_not_called()


# -- escalation ladder ---------------------------------------------------------


def test_restart_stage_notifies_then_schedules(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"max_restart_attempts": 3})
    app._escalate(usb_fault=True, evidence=["No supported devices found"])

    app.call_service.assert_called_once()  # only the notify; restart itself is deferred
    assert app.state["restart_attempts"] == 1
    app.run_in.assert_called_once()
    callback = app.run_in.call_args[0][0]
    assert callback == app._do_restart


def test_do_restart_calls_addon_restart_service(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"dry_run": False})
    app._do_restart({})
    app.call_service.assert_called_once_with("hassio/addon_restart", addon=app.addon_slug)


def test_dry_run_do_restart_never_calls_service(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"dry_run": True})
    app._do_restart({})
    app.call_service.assert_not_called()


def test_ladder_reaches_shutdown_after_attempts_exhausted(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"max_restart_attempts": 3})
    app.state["restart_attempts"] = 3
    app._shutdown_stage = Mock()

    app._escalate(usb_fault=True, evidence=["No supported devices found"])
    app._shutdown_stage.assert_called_once_with(True, ["No supported devices found"])


def test_generic_only_errors_never_reach_shutdown(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"max_restart_attempts": 3})
    app.state["restart_attempts"] = 3

    app._escalate(usb_fault=False, evidence=["Errno 111"])
    app.run_in.assert_not_called()
    app.call_service.assert_called_once()  # notify only


def test_shutdown_blocked_by_cooldown(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"min_shutdown_interval_hours": 24})
    app.state["restart_attempts"] = 3
    app.state["last_shutdown_ts"] = (app._now() - timedelta(hours=1)).isoformat()

    app._escalate(usb_fault=True, evidence=["No supported devices found"])
    app.run_in.assert_not_called()


def test_shutdown_blocked_while_pending_verification_even_after_cooldown(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"min_shutdown_interval_hours": 24})
    app.state["restart_attempts"] = 3
    app.state["last_shutdown_ts"] = (app._now() - timedelta(days=2)).isoformat()
    app.state["shutdown_pending_verification"] = True

    app._escalate(usb_fault=True, evidence=["No supported devices found"])
    app.run_in.assert_not_called()


def test_shutdown_state_written_before_scheduling_action(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    app.state["restart_attempts"] = 3

    saved_states = []
    original_save = app._save_state

    def record_save():
        saved_states.append(dict(app.state))
        original_save()

    app._save_state = record_save

    app._escalate(usb_fault=True, evidence=["No supported devices found"])

    assert saved_states, "state should have been saved before scheduling the shutdown"
    assert saved_states[-1]["shutdown_pending_verification"] is True
    app.run_in.assert_called_once()
    assert app.run_in.call_args[0][0] == app._do_proxmox_shutdown


def test_shutdown_notifies_both_services(monkeypatch, tmp_path):
    module, app = _make_app(
        monkeypatch,
        tmp_path,
        args={"secondary_notify_service": "notify/mobile_app_faro"},
    )
    app.state["restart_attempts"] = 3

    app._escalate(usb_fault=True, evidence=["No supported devices found"])

    services_called = [c.args[0] for c in app.call_service.call_args_list]
    assert "notify/mobile_app_wethop" in services_called
    assert "notify/mobile_app_faro" in services_called


def test_do_proxmox_shutdown_calls_rest_command(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"dry_run": False})
    app._do_proxmox_shutdown({})
    app.call_service.assert_called_once_with("rest_command/proxmox_shutdown")


def test_dry_run_proxmox_shutdown_never_calls_service(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path, args={"dry_run": True})
    app._do_proxmox_shutdown({})
    app.call_service.assert_not_called()


def test_recovery_resets_restart_and_shutdown_state(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    app.state["restart_attempts"] = 2
    app.state["shutdown_pending_verification"] = True
    _prep_for_check(app, stale=False, logs=None)

    app.check({})

    assert app.state["restart_attempts"] == 0
    assert app.state["shutdown_pending_verification"] is False


# -- persistence ----------------------------------------------------------------


def test_state_persists_across_reinitialization(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    app.state["restart_attempts"] = 2
    app._save_state()

    module2, app2 = _make_app(monkeypatch, tmp_path)
    assert app2.state["restart_attempts"] == 2


def test_corrupt_state_file_falls_back_to_defaults(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{not valid json")
    module, app = _make_app(monkeypatch, tmp_path)
    assert app.state["restart_attempts"] == 0
    assert app.state["shutdown_pending_verification"] is False


def test_state_write_failure_is_logged_not_raised(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", str(tmp_path / "missing_dir" / "state.json"))
    app.log.reset_mock()
    app._save_state()  # must not raise
    messages = [c.args[0] for c in app.log.call_args_list]
    assert any("could not write" in m for m in messages)


# -- notify robustness ----------------------------------------------------------


def test_notify_failure_does_not_block_restart_scheduling(monkeypatch, tmp_path):
    module, app = _make_app(monkeypatch, tmp_path)
    app.call_service = Mock(side_effect=Exception("notify down"))

    app._escalate(usb_fault=True, evidence=["No supported devices found"])

    app.run_in.assert_called_once()


# -- static config checks (no code execution) ------------------------------------


def test_apps_yaml_registers_rtlsdr_watchdog():
    config = APPS_YAML_PATH.read_text(encoding="utf-8")
    assert "rtlsdr_watchdog:" in config
    import re

    match = re.search(r"^rtlsdr_watchdog:\n(.*?)(?=^[A-Za-z0-9_]+:|\Z)", config, re.MULTILINE | re.DOTALL)
    assert match, "rtlsdr_watchdog block not found in apps.yaml"
    block = match.group(0)
    assert "module: rtlsdr_watchdog" in block
    assert "class: RtlSdrWatchdog" in block
    assert "dry_run: true" in block


def test_gitignore_whitelists_new_app_file():
    config = GITIGNORE_PATH.read_text(encoding="utf-8")
    assert "!appdaemon/apps/rtlsdr_watchdog.py" in config


def test_sync_script_excludes_watchdog_state_files():
    config = SYNC_SCRIPT_PATH.read_text(encoding="utf-8")
    assert ".rtlsdr_watchdog_state.json" in config
    assert ".last_host_reboot" in config
