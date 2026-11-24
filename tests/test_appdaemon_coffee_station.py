"""Coffee station state machine tests.

Everything here is simulated: a fake clock, a fake plug that follows (or
ignores) commands, and synthetic power traces. Nothing talks to a real plug.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "appdaemon" / "apps" / "coffee_station.py"
CHI = ZoneInfo("America/Chicago")
BREW_W = 1450.0


def _load_module():
    hassapi = types.ModuleType("hassapi")

    class Hass:
        pass

    hassapi.Hass = Hass
    sys.modules["hassapi"] = hassapi
    spec = importlib.util.spec_from_file_location("coffee_station_test_module", APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cs = _load_module()


def local(*args) -> datetime:
    return datetime(*args, tzinfo=CHI)


class Sim:
    """Drives CoffeeCore with a simulated clock, plug and telemetry."""

    def __init__(self, start: datetime, **cfg_args):
        args = {
            "liveness_entities": ["sensor.coffee_maker_voltage"],
            "power_on_behavior_entity": "select.coffee_maker_power_on_behavior",
            **cfg_args,
        }
        self.cfg = cs.CoffeeConfig.from_args(args)
        self.core = cs.CoffeeCore(self.cfg)
        self.now = start.astimezone(timezone.utc)
        self.timers: dict[str, tuple[datetime, int]] = {}
        self.effects: list[tuple] = []
        self.plug_commands: list[str] = []
        self.notifications: list[dict] = []
        self.plug_follows = True
        self.liveness = True
        self.next_liveness = self.now
        self.next_tick = self.now + timedelta(seconds=self.cfg.tick_s)
        self._pending: list[tuple] = []

    # -- setup -----------------------------------------------------------
    def start(self, *, plug="off", power=0.0, bed=False, bed_since=None, home=True, vacation=False,
              pob="off", previous=None, brews_since_descale=0, last_descale=None):
        snapshot = {
            "plug": plug, "power": power, "energy_kwh": 1.0, "telemetry_at": self.now,
            "bed": bed, "bed_since": bed_since or self.now - timedelta(hours=1), "bed_health_ok": True,
            "home": home, "vacation": vacation, "power_on_behavior": pob,
            "brews_since_descale": brews_since_descale, "last_descale": last_descale,
        }
        self.core.on_start(self.now, snapshot, previous)
        self._process()
        return self

    # -- effect processing -----------------------------------------------
    def _process(self):
        while True:
            effects = self.core.drain()
            if not effects and not self._pending:
                return
            for effect in effects:
                self.effects.append(effect)
                kind = effect[0]
                if kind == "timer":
                    _, name, delay, token = effect
                    self.timers[name] = (self.now + timedelta(seconds=delay), token)
                elif kind == "cancel_timer":
                    self.timers.pop(effect[1], None)
                elif kind == "plug":
                    self.plug_commands.append(effect[1])
                    if self.plug_follows:
                        self._pending.append(("plug", effect[1]))
                elif kind == "notify":
                    self.notifications.append(effect[1])
            pending, self._pending = self._pending, []
            for item in pending:
                if item[0] == "plug" and self.core.plug != item[1] and self.core.plug is not None:
                    self.core.on_plug(item[1], self.now)
                    if item[1] == "off":
                        self.core.on_power(0.0, self.now)

    # -- inputs ----------------------------------------------------------
    def remote(self, action):
        self.core.on_remote(action, self.now)
        self._process()

    def request(self, kind, source="dashboard"):
        self.core.request(kind, source, self.now)
        self._process()

    def bed(self, occupied):
        self.core.on_bed(occupied, self.now)
        self._process()

    def presence(self, home):
        self.core.on_presence(home, self.now)
        self._process()

    def vacation(self, active):
        self.core.on_vacation(active, self.now)
        self._process()

    def power(self, watts):
        # A working plug that reports off draws nothing; only a test that
        # simulates a misbehaving plug (plug_follows=False) can say otherwise.
        if self.plug_follows and self.core.plug == "off" and watts:
            watts = 0.0
        self.core.on_power(watts, self.now)
        self._process()

    def plug(self, state):
        self.core.on_plug(state, self.now)
        self._process()

    def advance(self, seconds: float):
        target = self.now + timedelta(seconds=seconds)
        while True:
            candidates = [(due, "timer", name) for name, (due, _) in self.timers.items()]
            candidates.append((self.next_tick, "tick", None))
            if self.liveness:
                candidates.append((self.next_liveness, "liveness", None))
            due, kind, name = min(candidates, key=lambda c: c[0])
            if due > target:
                break
            self.now = max(self.now, due)
            if kind == "timer":
                _, token = self.timers.pop(name)
                self.core.on_timer(name, token, self.now)
            elif kind == "tick":
                self.next_tick = self.now + timedelta(seconds=self.cfg.tick_s)
                self.core.tick(self.now)
            else:
                self.next_liveness = self.now + timedelta(seconds=10)
                self.core.on_telemetry(self.now)
            self._process()
        self.now = target

    def advance_to(self, when: datetime):
        self.advance((when.astimezone(timezone.utc) - self.now).total_seconds())

    def heat(self, seconds: float, watts: float = BREW_W, step: float = 5.0):
        """Feed a steady heating trace (the plug reports every `step` s)."""
        elapsed = 0.0
        while elapsed < seconds:
            self.power(watts)
            chunk = min(step, seconds - elapsed)
            self.advance(chunk)
            elapsed += chunk

    # -- assertions helpers ----------------------------------------------
    @property
    def state(self):
        return self.core.state

    def kinds(self):
        return [n["kind"] for n in self.notifications]

    def counters(self):
        return [(e[1], e[2]) for e in self.effects if e[0] == "counter"]


def armed_evening(start=local(2026, 11, 24, 21, 0), **cfg):
    """Tuesday evening: arm at 21:00, in bed from 22:00."""
    sim = Sim(start, **cfg).start(bed=False)
    sim.remote("on")
    assert sim.state == cs.ARMED
    sim.advance_to(start + timedelta(hours=1))
    sim.bed(True)
    return sim


def full_brew(sim, heating_s=360):
    sim.heat(heating_s)
    sim.power(0.0)
    sim.advance(30)  # completion debounce
    assert sim.state == cs.DRAINING
    sim.advance(90)  # drainage
    return sim


# ---------------------------------------------------------------------------
# Normal operation
# ---------------------------------------------------------------------------


def test_normal_evening_arming_and_morning_brew():
    sim = armed_evening()
    assert sim.notifications[-1]["kind"] == "armed"
    assert sim.core.armed_until == local(2026, 11, 25, 11, 0).astimezone(timezone.utc)
    sim.advance_to(local(2026, 11, 25, 6, 30))
    assert sim.state == cs.ARMED
    sim.bed(False)
    assert sim.state == cs.WAITING
    sim.advance(299)
    assert sim.state == cs.WAITING and sim.plug_commands == []
    sim.advance(1)
    assert sim.state == cs.STARTING
    assert sim.plug_commands == ["on"]
    assert sim.core.armed_at is None, "arming is consumed when brewing begins"
    sim.power(BREW_W)
    sim.advance(10)
    assert sim.state == cs.BREWING
    full_brew(sim, heating_s=350)
    assert sim.state == cs.READY
    assert sim.plug_commands == ["on", "off"]
    assert sim.core.plug == "off"
    assert ("total", "increment") in sim.counters()
    assert ("since_descale", "increment") in sim.counters()
    record = [e[1] for e in sim.effects if e[0] == "record_brew"][0]
    assert record["success"] and 350 <= record["heating_s"] <= 370
    assert record["peak_power_w"] == BREW_W
    assert record["source"] == "wake-up"
    assert "ready" in sim.kinds()
    # A second wake-up the same morning never brews again.
    sim.advance(3600)
    assert sim.state == cs.IDLE
    sim.bed(True)
    sim.advance(3600)
    sim.bed(False)
    sim.advance(600)
    assert sim.plug_commands == ["on", "off"]


def test_ready_only_after_drainage_and_confirmed_shutdown():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(False)
    sim.advance(300)
    sim.heat(400)
    sim.power(3.0)  # below completion threshold
    sim.advance(29)
    assert sim.state == cs.BREWING
    sim.advance(1)
    assert sim.state == cs.DRAINING
    assert sim.plug_commands[-1] == "off"
    sim.advance(89)
    assert sim.state == cs.DRAINING
    sim.advance(1)
    assert sim.state == cs.READY


def test_brew_now_while_armed_and_long_press_repeats_brew_once():
    sim = armed_evening()
    sim.remote("brightness_move_up")
    assert sim.state == cs.STARTING
    sim.advance(0.5)
    sim.remote("brightness_move_up")  # Z2M repeat / duplicate
    sim.advance(3)
    sim.remote("brightness_move_up")
    sim.remote("brightness_stop")
    sim.advance(2)
    sim.remote("brightness_move_up")  # a fresh long press while starting
    assert sim.plug_commands == ["on"]
    assert sim.core.brew.source == "remote"


def test_brew_now_while_unarmed_is_refused():
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    sim.remote("brightness_move_up")
    assert sim.state == cs.IDLE
    assert sim.plug_commands == []
    assert sim.notifications[-1]["kind"] == "brew_refused"


def test_duplicate_remote_events_are_idempotent():
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    sim.remote("on")
    sim.advance(0.3)
    sim.remote("on")
    sim.advance(5)
    sim.remote("on")  # a later press while armed is a no-op, not a re-arm
    assert sim.kinds().count("armed") == 1
    arming = [e for e in sim.effects if e[0] == "timer" and e[1] == "arming_expiry"]
    assert len(arming) == 1


# ---------------------------------------------------------------------------
# Wake-up detection
# ---------------------------------------------------------------------------


def test_overnight_bathroom_trip_does_not_trigger():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 2, 0))
    sim.bed(False)
    assert sim.state == cs.ARMED
    assert "outside the morning window" in sim.core.last_ignored
    sim.advance(15 * 60)
    sim.bed(True)
    assert sim.plug_commands == []
    # The real wake-up still works (sleep session restarted at 02:15).
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(False)
    sim.advance(300)
    assert sim.state == cs.STARTING


def test_window_opening_alone_does_not_trigger():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 5, 30))
    assert sim.state == cs.ARMED and sim.plug_commands == []


def test_bed_already_empty_at_window_start_does_not_trigger():
    sim = Sim(local(2026, 11, 24, 21, 0)).start(bed=False)
    sim.remote("on")
    sim.advance_to(local(2026, 11, 25, 7, 0))
    sim.bed(False)  # duplicate vacant update, not a transition
    sim.advance(600)
    assert sim.state == cs.ARMED and sim.plug_commands == []


def test_returning_to_bed_before_debounce_cancels_and_keeps_session():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 0))
    sim.bed(False)
    assert sim.state == cs.WAITING
    sim.advance(180)
    sim.bed(True)
    assert sim.state == cs.ARMED
    assert not sim.core.timer_active("vacancy")
    sim.advance(600)
    assert sim.plug_commands == []
    # Getting up for real 30 min later still qualifies: a short trip does not
    # reset the preceding-occupancy clock.
    sim.advance(1800)
    sim.bed(False)
    sim.advance(300)
    assert sim.state == cs.STARTING


def test_insufficient_prior_occupancy_is_ignored():
    sim = Sim(local(2026, 11, 24, 21, 0)).start(bed=False)
    sim.remote("on")
    sim.advance_to(local(2026, 11, 25, 6, 0))
    sim.bed(True)
    sim.advance(30 * 60)
    sim.bed(False)
    assert sim.state == cs.ARMED
    assert "preceding bed occupancy" in sim.core.last_ignored


def test_weekend_window_is_used_on_saturday():
    sim = Sim(local(2026, 11, 27, 21, 0), weekend_window=["07:00", "12:00"]).start()
    sim.remote("on")
    assert sim.core.window.start == local(2026, 11, 28, 7, 0).astimezone(timezone.utc)
    assert sim.core.armed_until == local(2026, 11, 28, 12, 0).astimezone(timezone.utc)


def test_invalid_bed_state_blocks_and_resets_waiting():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(False)
    assert sim.state == cs.WAITING
    sim.bed(None)
    assert sim.state == cs.ARMED
    sim.advance(600)
    assert sim.plug_commands == []


def test_bed_health_sensor_unavailable_blocks_wakeup():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.core.on_bed_health(False, sim.now)
    sim.bed(False)
    assert sim.state == cs.ARMED
    assert "sensors unavailable" in sim.core.last_ignored


# ---------------------------------------------------------------------------
# Arming lifecycle
# ---------------------------------------------------------------------------


def test_cancellation_before_brewing():
    sim = armed_evening()
    sim.remote("off")
    assert sim.state == cs.CANCELLED
    # OFF is always sent (our view of the plug could be stale) and confirms at once.
    assert sim.plug_commands == ["off"]
    assert sim.core.shutdown is None
    sim.advance(60)
    assert sim.state == cs.IDLE


def test_cancellation_during_brewing():
    sim = armed_evening()
    sim.request("brew_now", "remote")
    sim.power(BREW_W)
    sim.advance(60)
    assert sim.state == cs.BREWING
    sim.remote("off")
    assert sim.state == cs.CANCELLED
    assert sim.plug_commands == ["on", "off"]
    assert sim.core.shutdown is None, "shutdown confirmed"
    assert ("failed", "increment") in sim.counters()


def test_departure_disarms():
    sim = armed_evening()
    sim.presence(False)
    assert sim.state == cs.CANCELLED
    assert "left home" in sim.core.transition_reason


def test_departure_during_brew_stops_it():
    sim = armed_evening()
    sim.request("brew_now", "remote")
    sim.power(BREW_W)
    sim.advance(20)
    sim.presence(False)
    assert sim.state == cs.CANCELLED
    assert sim.plug_commands[-1] == "off"


def test_vacation_mode_disarms():
    sim = armed_evening()
    sim.vacation(True)
    assert sim.state == cs.CANCELLED


def test_arming_expires_at_window_end():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 10, 59))
    assert sim.state == cs.ARMED
    sim.advance(60)
    assert sim.state == cs.CANCELLED
    assert "expired" in sim.core.transition_reason


def test_maximum_arming_duration_caps_arming():
    sim = Sim(local(2026, 11, 24, 21, 0), max_arming_s=10 * 3600).start()
    sim.remote("on")
    assert sim.core.armed_until == local(2026, 11, 25, 7, 0).astimezone(timezone.utc)


def test_arming_too_early_is_refused():
    sim = Sim(local(2026, 11, 24, 9, 0)).start()
    sim.remote("on")  # tomorrow 05:00 is 20 h away
    assert sim.state == cs.IDLE
    assert "Arm after 11:00" in sim.notifications[-1]["message"]


def test_arming_requires_home_and_plug_off():
    sim = Sim(local(2026, 11, 24, 21, 0)).start(home=False)
    sim.remote("on")
    assert sim.state == cs.IDLE
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    sim.plug_follows = False
    sim.core.plug = "on"
    sim.remote("on")
    assert sim.state == cs.IDLE


# ---------------------------------------------------------------------------
# Power monitoring
# ---------------------------------------------------------------------------


def brewing(sim=None):
    sim = sim or armed_evening()
    sim.request("brew_now", "remote")
    sim.power(BREW_W)
    sim.advance(10)
    assert sim.state == cs.BREWING
    return sim


def test_failure_to_detect_heating():
    sim = armed_evening()
    sim.request("brew_now", "remote")
    sim.power(2.0)
    sim.advance(30)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "failed_to_start"
    assert sim.plug_commands == ["on", "off"]
    assert sim.core.shutdown is None
    assert ("failed", "increment") in sim.counters()


def test_brief_heating_interruption_is_not_completion():
    sim = brewing()
    sim.heat(120)
    sim.power(0.0)
    sim.advance(10)
    sim.power(BREW_W)
    assert sim.state == cs.BREWING
    assert sim.core.brew.interruptions == 1
    sim.heat(240)
    sim.power(0.0)
    sim.advance(120)
    assert sim.state == cs.READY


def test_unexpectedly_short_brew():
    sim = brewing()
    sim.heat(60)
    sim.power(0.0)
    sim.advance(30)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "short_brew"
    assert sim.plug_commands[-1] == "off"


def test_stale_power_telemetry_during_brew():
    sim = brewing()
    sim.liveness = False
    sim.advance(100)
    assert sim.state == cs.BREWING, "a quiet gap shorter than telemetry_stale_s is tolerated"
    sim.advance(60)  # no power or liveness updates at all for > 120 s
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "stale_telemetry"
    assert sim.plug_commands[-1] == "off"


def test_power_sensor_unavailable_during_brew():
    sim = brewing()
    sim.power(None)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "telemetry_lost"


def test_maximum_runtime_exceeded():
    sim = brewing()
    sim.heat(13 * 60)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "excessive_runtime"
    assert sim.plug_commands[-1] == "off"


def test_plug_unavailable_during_brew_is_critical():
    sim = brewing()
    sim.plug(None)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "plug_unavailable_during_brew"
    assert sim.notifications[-1]["level"] == "critical"


def test_plug_unavailable_while_armed_disarms():
    sim = armed_evening()
    sim.plug(None)
    assert sim.state == cs.UNAVAILABLE
    assert "disarmed_unavailable" in sim.kinds()
    sim.plug("off")
    assert sim.state == cs.IDLE


def test_failed_shutdown_confirmation_escalates():
    sim = brewing()
    sim.plug_follows = False
    sim.remote("off")
    assert sim.core.shutdown is not None
    sim.advance(45)
    assert sim.plug_commands.count("off") == 4, "three retries before escalating"
    assert sim.state == cs.CANCELLED
    sim.advance(15)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "shutdown_unconfirmed"
    assert sim.notifications[-1]["level"] == "critical"
    # OFF keeps being re-sent every minute, but the critical page backs off.
    sim.advance(10 * 60)
    assert sum(n["level"] == "critical" for n in sim.notifications) == 1
    assert sim.plug_commands.count("off") >= 12
    sim.advance(6 * 60)
    assert sum(n["level"] == "critical" for n in sim.notifications) == 2
    # Acknowledging is refused while the plug is still not confirmed off.
    sim.remote("brightness_move_down")
    assert sim.state == cs.FAULT
    # Once the plug really reports off, the fault can be acknowledged.
    sim.plug("off")
    sim.power(0.0)
    sim.remote("brightness_stop")
    sim.advance(2)
    sim.remote("brightness_move_down")
    assert sim.state == cs.IDLE


def test_unexpected_plug_activation_is_switched_off_by_default():
    """Default policy: only an armed station may brew. A plug turned on from
    the Eve app, Siri, Home or its button is switched straight back off."""
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    sim.plug("on")
    assert sim.state == cs.IDLE
    assert sim.plug_commands == ["off"]
    assert "manual_shutoff" in sim.kinds()
    # Even while armed: a manual plug-on is not a brew-now.
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    sim.remote("on")
    sim.plug("on")
    assert sim.plug_commands == ["off"]
    assert sim.core.brew is None


def test_unexpected_plug_activation_supervised_only_when_opted_in():
    sim = Sim(local(2026, 11, 24, 21, 0), manual_activation_policy="supervise_if_home").start()
    sim.plug("on")
    assert sim.state == cs.STARTING
    assert sim.core.brew.source == "manual plug activation"
    assert sim.plug_commands == []
    sim.advance(30)  # no heating -> fault + off
    assert sim.state == cs.FAULT


def test_unexpected_plug_activation_shutoff_policy_and_away():
    sim = Sim(local(2026, 11, 24, 21, 0), manual_activation_policy="shutoff").start()
    sim.plug("on")
    assert sim.state == cs.IDLE
    assert sim.plug_commands == ["off"]
    sim = Sim(local(2026, 11, 24, 21, 0), manual_activation_policy="supervise_if_home").start(home=False)
    sim.plug("on")
    assert sim.plug_commands == ["off"]


def test_stop_works_in_every_state():
    for prepare in (
        lambda s: None,
        lambda s: s.remote("on"),
        lambda s: (s.remote("on"), s.request("brew_now")),
    ):
        sim = Sim(local(2026, 11, 24, 21, 0)).start()
        prepare(sim)
        sim.plug_follows = True
        sim.core.plug = "on"  # whatever happened, the plug is on
        sim.request("stop")
        assert sim.plug_commands[-1] == "off"


# ---------------------------------------------------------------------------
# Restarts, outages, connectivity
# ---------------------------------------------------------------------------


def test_home_assistant_restart_disarms_and_never_brews():
    sim = Sim(local(2026, 11, 25, 6, 30)).start(bed=True, previous={"armed": True, "state": "armed"})
    assert sim.state == cs.IDLE
    assert sim.kinds() == ["restart_disarmed"]
    sim.bed(False)
    sim.advance(600)
    assert sim.plug_commands == []


def test_appdaemon_restart_with_plug_energized_switches_it_off():
    sim = Sim(local(2026, 11, 25, 6, 30)).start(plug="on", power=BREW_W,
                                                 previous={"active": True, "state": "brewing"})
    assert sim.plug_commands == ["off"]
    assert sim.core.plug == "off"
    assert sim.state == cs.IDLE
    assert {"restart_disarmed", "startup_shutoff"} <= set(sim.kinds())


def test_mqtt_interruption_remote_unavailable_dashboard_still_works():
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    sim.remote(None)  # adapter maps unavailable/"" to no action
    assert sim.state == cs.IDLE
    sim.request("arm", "dashboard")
    assert sim.state == cs.ARMED
    # Z2M replays the last action after reconnecting: still idempotent.
    sim.remote("on")
    assert sim.kinds().count("armed") == 1


def test_power_outage_and_restoration():
    sim = armed_evening()
    sim.plug(None)  # outage: plug drops off the network
    sim.power(None)
    assert sim.state == cs.UNAVAILABLE
    sim.plug("on")  # comes back energized (restore-to-previous)
    assert sim.state == cs.FAULT
    assert sim.core.fault_reason == "energized_after_power_restore"
    assert sim.plug_commands[-1] == "off"


def test_power_on_behavior_must_be_off():
    sim = Sim(local(2026, 11, 24, 21, 0)).start(pob="previous")
    assert ("set_power_on_behavior", "off") in sim.effects
    assert sim.state == cs.UNAVAILABLE
    sim.remote("on")
    assert sim.state == cs.UNAVAILABLE
    sim.core.on_power_on_behavior("off", sim.now)
    sim._process()
    assert sim.state == cs.IDLE


def test_stale_timer_callbacks_are_ignored():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(False)
    _, token = sim.timers["vacancy"]
    sim.bed(True)
    sim.core.on_timer("vacancy", token, sim.now + timedelta(minutes=5))
    sim._process()
    assert sim.state == cs.ARMED and sim.plug_commands == []


# ---------------------------------------------------------------------------
# Daylight saving time
# ---------------------------------------------------------------------------


def test_spring_forward_window_and_expiry():
    sim = Sim(local(2026, 3, 7, 22, 0)).start()
    sim.remote("on")
    assert sim.core.window.start == datetime(2026, 3, 8, 10, 0, tzinfo=timezone.utc)  # 05:00 CDT
    assert sim.core.armed_until == datetime(2026, 3, 8, 16, 0, tzinfo=timezone.utc)  # 11:00 CDT
    sim.advance_to(local(2026, 3, 8, 10, 59, 30))
    assert sim.state == cs.ARMED
    sim.advance(60)
    assert sim.state == cs.CANCELLED


def test_fall_back_brew_uses_real_elapsed_time():
    sim = Sim(local(2026, 10, 31, 22, 0)).start(bed=False)
    sim.remote("on")
    assert sim.core.window.start == datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)  # 05:00 CST
    # In bed at 01:30 CDT; the clock repeats 01:00-02:00, so 05:10 CST is 4 h 40 min later.
    sim.advance_to(datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc))
    sim.bed(True)
    sim.advance_to(local(2026, 11, 1, 5, 10))
    sim.bed(False)
    sim.advance(300)
    assert sim.state == cs.STARTING


# ---------------------------------------------------------------------------
# Faults, maintenance, profiles
# ---------------------------------------------------------------------------


def test_fault_latches_until_acknowledged():
    sim = armed_evening()
    sim.request("brew_now")
    sim.advance(30)
    assert sim.state == cs.FAULT
    sim.remote("on")
    assert sim.state == cs.FAULT
    assert "Acknowledge the fault" in sim.notifications[-1]["message"]
    sim.remote("off")  # short OFF stops but does not acknowledge
    assert sim.state == cs.FAULT
    sim.advance(2)
    sim.remote("brightness_move_down")
    assert sim.state == cs.IDLE
    assert ("clear_notification", cs.TAG_FAULT) in sim.effects


def test_maintenance_due_after_configured_brews_and_reset():
    sim = Sim(local(2026, 11, 24, 21, 0), descale_brews=3).start(brews_since_descale=2)
    sim.remote("on")
    brewing(sim)
    full_brew(sim)
    assert sim.state == cs.READY
    assert "maintenance" in sim.kinds()
    assert sim.core.maintenance_due(sim.now)
    sim.request("reset_maintenance")
    assert not sim.core.maintenance_due(sim.now)
    assert ("counter", "since_descale", "reset") in sim.effects


def test_maintenance_due_by_date():
    sim = Sim(local(2026, 11, 24, 21, 0), descale_days=30).start(
        last_descale=local(2026, 10, 1, 12, 0).astimezone(timezone.utc))
    sim.advance(60)
    assert "maintenance" in sim.kinds()
    sim.advance(3600)
    assert sim.kinds().count("maintenance") == 1


def test_glass_hotplate_profile_completes_on_plate_level_power():
    sim = Sim(local(2026, 11, 24, 21, 0), profile="glass_hotplate").start()
    sim.remote("on")
    brewing(sim)
    sim.heat(300)
    sim.heat(30, watts=80.0)  # warming plate cycling, not heating
    assert sim.state == cs.DRAINING
    sim.advance(90)
    assert sim.state == cs.READY


def test_keep_warm_leaves_plate_on_then_switches_off():
    sim = Sim(local(2026, 11, 24, 21, 0), profile="glass_hotplate", keep_warm_s=600).start()
    sim.remote("on")
    brewing(sim)
    sim.heat(300)
    sim.power(80.0)
    sim.advance(30)
    assert sim.state == cs.DRAINING and sim.plug_commands == ["on"]
    sim.heat(90, watts=80.0)
    assert sim.state == cs.READY and sim.core.plug == "on"
    sim.heat(600, watts=80.0)
    assert sim.plug_commands[-1] == "off" and sim.core.plug == "off"
    assert sim.state == cs.READY


def test_transition_table_rejects_invalid_moves():
    sim = Sim(local(2026, 11, 24, 21, 0)).start()
    assert not sim.core._transition(cs.BREWING, "bogus", sim.now)
    assert sim.state == cs.IDLE
    for state, targets in cs.VALID_TRANSITIONS.items():
        assert state in cs.ALL_STATES
        assert targets <= set(cs.ALL_STATES)
    assert cs.VALID_TRANSITIONS[cs.FAULT] == {cs.IDLE}


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        cs.CoffeeConfig.from_args({"weekday_window": ["11:00", "05:00"]})
    with pytest.raises(ValueError):
        cs.CoffeeConfig.from_args({"profile": "espresso"})
    with pytest.raises(ValueError):
        cs.CoffeeConfig.from_args({"idle_threshold_w": 600})


# ---------------------------------------------------------------------------
# AppDaemon adapter
# ---------------------------------------------------------------------------

ARGS = {
    "switch_entity": "switch.coffee_maker",
    "power_entity": "sensor.coffee_maker_power",
    "energy_entity": "sensor.coffee_maker_energy",
    "liveness_entities": ["sensor.coffee_maker_voltage"],
    "power_on_behavior_entity": "select.coffee_maker_power_on_behavior",
    "remote_action_entity": "sensor.coffee_station_remote_action",
    "bed_entity": "input_boolean.master_bed_occupancy",
    "presence_entity": "binary_sensor.example_home",
    "vacation_entities": ["input_boolean.trip"],
    "notify_service": "notify/all",
    "arm_button": "input_button.coffee_arm",
    "total_brews_counter": "counter.coffee_total_brews",
}


def make_adapter(monkeypatch, tmp_path, states, args=None, previous=None):
    monkeypatch.setattr(cs, "STATE_FILE", str(tmp_path / "state.json"))
    if previous is not None:
        (tmp_path / "state.json").write_text(json.dumps(previous))
    app = cs.CoffeeStation.__new__(cs.CoffeeStation)
    app.args = dict(ARGS if args is None else args)
    app.log = Mock()
    app.call_service = Mock()
    app.set_state = Mock()
    app.listen_state = Mock()
    app.listen_event = Mock()
    app.run_every = Mock()
    app.cancel_timer = Mock()
    handles = iter(range(1000))
    app.run_in = Mock(side_effect=lambda *a, **k: next(handles))
    now = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
    app.get_now = Mock(return_value=now)
    stamp = now.isoformat()

    def get_state(entity_id, attribute=None):
        value = states.get(entity_id)
        if value is None:
            return None
        return {"state": value, "last_changed": stamp, "last_updated": stamp, "last_reported": stamp}

    app.get_state = Mock(side_effect=get_state)
    cs.CoffeeStation.initialize(app)
    return app


HEALTHY = {
    "switch.coffee_maker": "off",
    "sensor.coffee_maker_power": "0.0",
    "sensor.coffee_maker_energy": "1.2",
    "sensor.coffee_maker_voltage": "121.7",
    "select.coffee_maker_power_on_behavior": "off",
    "input_boolean.master_bed_occupancy": "off",
    "binary_sensor.example_home": "on",
    "input_boolean.trip": "off",
}


def test_adapter_disabled_without_required_args(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY, args={"switch_entity": "switch.coffee_maker"})
    assert app.core is None
    app.listen_state.assert_not_called()


def test_adapter_publishes_entities_and_switches_off_energized_plug(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, {**HEALTHY, "switch.coffee_maker": "on"},
                       previous={"armed": True})
    app.call_service.assert_any_call("switch/turn_off", entity_id="switch.coffee_maker")
    published = {c.args[0]: c.kwargs["state"] for c in app.set_state.call_args_list}
    assert published["sensor.coffee_state"] == "idle"
    for entity in ("binary_sensor.coffee_armed", "binary_sensor.coffee_brewing", "binary_sensor.coffee_ready",
                   "binary_sensor.coffee_station_available", "sensor.coffee_fault", "sensor.coffee_armed_until",
                   "sensor.coffee_next_window", "sensor.coffee_brew_progress", "binary_sensor.coffee_maintenance_due"):
        assert entity in published
    notify_calls = [c for c in app.call_service.call_args_list if c.args[0] == "notify/all"]
    assert notify_calls, "restart/startup notices go through the configured notify service"
    data = notify_calls[0].kwargs["data"]
    assert data["tag"].startswith("coffee_station")
    assert data["url"] == data["clickAction"] == "/db-coffee/coffee"


def test_adapter_critical_notification_payload(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app.call_service.reset_mock()
    app._notify({"kind": "fault", "title": "t", "message": "m", "tag": cs.TAG_FAULT, "level": "critical",
                 "actions": ["COFFEE_STOP"]})
    calls = {c.args[0]: c.kwargs for c in app.call_service.call_args_list}
    data = calls["notify/all"]["data"]
    assert data["push"]["sound"]["critical"] == 1
    assert data["actions"][0] == {"action": "COFFEE_STOP", "title": "Stop coffee"}
    assert data["channel"] == "alarm_stream" and data["priority"] == "high"
    # Faults also land as a local persistent notification.
    assert calls["persistent_notification/create"]["notification_id"] == "coffee_station_fault"


def test_adapter_button_and_notification_action_routing(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app._cb_button("input_button.coffee_arm", "state", None, "2026-11-25T03:00:00+00:00", {"kind": "arm"})
    assert app.core.state == cs.IDLE, "helper reload (old=None) is not a press"
    app.get_now.return_value = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
    app._cb_button("input_button.coffee_arm", "state", "2026-11-24T00:00:00+00:00",
                   "2026-11-25T03:00:00+00:00", {"kind": "arm"})
    assert app.core.state == cs.ARMED
    app._cb_notification_action("mobile_app_notification_action", {"action": "COFFEE_DISARM"}, {})
    assert app.core.state == cs.CANCELLED


def test_adapter_timer_effects_use_run_in_and_cancel(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app._cb_button("input_button.coffee_arm", "state", "a", "b", {"kind": "arm"})
    assert "arming_expiry" in app._handles
    kwargs = app.run_in.call_args.kwargs
    assert kwargs["timer_name"] == "arming_expiry" and isinstance(kwargs["token"], int)
    app._cb_notification_action("mobile_app_notification_action", {"action": "COFFEE_DISARM"}, {})
    app.cancel_timer.assert_called()
    assert "arming_expiry" not in app._handles


def test_adapter_home_assistant_reconnect_resyncs(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app._cb_button("input_button.coffee_arm", "state", "a", "b", {"kind": "arm"})
    assert app.core.state == cs.ARMED
    app._cb_plugin_started("plugin_started", {}, {})
    assert app.core.state == cs.IDLE
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["armed"] is False


def test_adapter_callback_errors_fail_safe(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app.call_service.reset_mock()
    app.core.on_power = Mock(side_effect=RuntimeError("boom"))
    app._cb_power("sensor.coffee_maker_power", "state", "0", "1450", {})
    app.call_service.assert_any_call("switch/turn_off", entity_id="switch.coffee_maker")


def test_every_state_has_a_distinct_material_design_icon():
    assert set(cs.STATE_ICONS) == set(cs.ALL_STATES)
    assert len(set(cs.STATE_ICONS.values())) == len(cs.ALL_STATES)
    assert all(icon.startswith("mdi:") for icon in cs.STATE_ICONS.values())
    for on_icon, off_icon in cs.BINARY_ICONS.values():
        assert on_icon != off_icon


def test_published_icons_follow_the_state(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)

    def icons():
        latest = {}
        for c in app.set_state.call_args_list:
            latest[c.args[0]] = c.kwargs["attributes"]["icon"]
        return latest

    assert icons()["sensor.coffee_state"] == cs.STATE_ICONS[cs.IDLE]
    assert icons()["binary_sensor.coffee_armed"] == "mdi:coffee-maker-outline"
    app._cb_button("input_button.coffee_arm", "state", "a", "b", {"kind": "arm"})
    assert icons()["sensor.coffee_state"] == cs.STATE_ICONS[cs.ARMED]
    assert icons()["binary_sensor.coffee_armed"] == "mdi:coffee-maker-check"
    app._cb_notification_action("mobile_app_notification_action", {"action": "COFFEE_DISARM"}, {})
    assert icons()["sensor.coffee_state"] == cs.STATE_ICONS[cs.CANCELLED]


# ---------------------------------------------------------------------------
# Regressions from the expert reviews
# ---------------------------------------------------------------------------


def drained(sim=None):
    sim = brewing(sim)
    sim.heat(300)
    sim.power(0.0)
    sim.advance(30)
    assert sim.state == cs.DRAINING and sim.core.plug == "off"
    return sim


def test_plug_switched_on_during_drainage_is_switched_off():
    sim = drained()
    sim.plug_follows = False
    sim.plug("on")
    assert sim.plug_commands[-1] == "off"
    assert sim.core.shutdown is not None, "supervised: confirmation pending"
    sim.plug("off")
    sim.power(0.0)
    sim.advance(90)
    assert sim.state == cs.READY


def test_keep_warm_never_outlives_the_ready_hold():
    with pytest.raises(ValueError):
        cs.CoffeeConfig.from_args({"profile": "glass_hotplate", "keep_warm_s": 5400})
    sim = Sim(local(2026, 11, 24, 21, 0), profile="glass_hotplate", keep_warm_s=1800, ready_hold_s=1900).start()
    sim.remote("on")
    brewing(sim)
    sim.heat(300)
    sim.power(80.0)
    sim.advance(120)
    assert sim.state == cs.READY and sim.core.plug == "on"
    # Losing the keep-warm timer is caught by max_energized (keep_warm + 60 s)...
    sim.core._cancel("keep_warm")
    sim._process()
    sim.advance(1900)
    assert sim.core.plug == "off"
    assert sim.core.fault_reason == "excessive_runtime"
    # ...and even with both gone, the hold timer switches the plate off.
    sim = Sim(local(2026, 11, 24, 21, 0), profile="glass_hotplate", keep_warm_s=1800, ready_hold_s=1900).start()
    sim.remote("on")
    brewing(sim)
    sim.heat(300)
    sim.power(80.0)
    sim.advance(120)
    sim.core._cancel("keep_warm")
    sim.core._cancel("max_energized")
    sim._process()
    sim.advance(1900)
    assert sim.state == cs.IDLE
    assert sim.core.plug == "off"


def test_bed_sensor_dropout_does_not_swallow_the_wakeup():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(None)  # brief dropout while still in bed
    sim.bed(False)  # comes back vacant: a real transition from the last valid value
    assert sim.state == cs.WAITING
    sim.advance(300)
    assert sim.state == cs.STARTING


def test_bed_sensor_dropout_does_not_reset_the_sleep_session():
    sim = armed_evening()
    sim.advance_to(local(2026, 11, 25, 6, 0))
    sim.bed(None)
    sim.advance(5)
    sim.bed(True)  # recovery to the same value: not a new session
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(False)
    assert sim.state == cs.WAITING


def test_plug_unavailable_after_confirmed_off_is_not_a_fault():
    sim = drained()
    sim.plug(None)
    assert sim.state == cs.DRAINING
    sim.advance(90)
    # Drainage completes on the earlier confirmed OFF (the station then shows
    # unavailable because the plug really is unreachable) - no fault.
    assert "ready" in sim.kinds()
    assert ("total", "increment") in sim.counters()
    assert sim.core.last_fault_reason is None


def test_fault_latch_survives_a_restart():
    sim = armed_evening()
    sim.request("brew_now")
    sim.advance(30)
    assert sim.state == cs.FAULT
    persisted = [e[1] for e in sim.effects if e[0] == "persist"][-1]
    assert persisted["fault_reason"] == "failed_to_start"
    restarted = Sim(local(2026, 11, 24, 23, 0)).start(previous=persisted)
    assert restarted.state == cs.FAULT
    assert restarted.core.fault_reason == "failed_to_start"
    restarted.remote("on")
    assert restarted.state == cs.FAULT


def test_restart_clears_a_stale_fault_reason_when_not_faulted():
    sim = Sim(local(2026, 11, 24, 21, 0))
    sim.core.fault_reason = "short_brew"
    sim.start(previous={"state": "idle"})
    assert sim.state == cs.IDLE and sim.core.fault_reason is None


def test_restart_during_brew_counts_an_interrupted_brew():
    sim = Sim(local(2026, 11, 25, 6, 30)).start(previous={"active": True, "state": "brewing"})
    assert ("failed", "increment") in sim.counters()


def test_quiet_telemetry_overnight_does_not_cancel_the_arming():
    sim = armed_evening()
    sim.liveness = False
    sim.advance(2 * 3600)
    assert sim.state == cs.ARMED, "soft issue: stays armed"
    assert "plug telemetry stale" in sim.core.station_issues(sim.now)
    # ...but a brew never starts on stale telemetry.
    sim.advance_to(local(2026, 11, 25, 6, 30))
    sim.bed(False)
    sim.advance(300)
    assert "telemetry stale" in [n for n in sim.notifications if n["kind"] == "cancelled"][-1]["message"]
    assert sim.state in (cs.CANCELLED, cs.UNAVAILABLE)
    assert sim.plug_commands == []
    sim.liveness = True
    sim.advance(120)
    assert sim.state == cs.IDLE


def test_unknown_power_on_behavior_does_not_disarm():
    sim = armed_evening()
    sim.core.on_power_on_behavior(None, sim.now)
    sim._process()
    assert sim.state == cs.ARMED
    sim.core.on_power_on_behavior("previous", sim.now)
    sim._process()
    assert sim.state == cs.UNAVAILABLE


def test_adapter_missing_power_on_behavior_entity_does_not_lock_out(monkeypatch, tmp_path):
    states = {k: v for k, v in HEALTHY.items() if k != "select.coffee_maker_power_on_behavior"}
    app = make_adapter(monkeypatch, tmp_path, states)
    assert app.core.state == cs.IDLE
    assert not app.core.cfg.has_power_on_behavior
    assert any(c.kwargs.get("level") == "ERROR" for c in app.log.call_args_list)


def test_adapter_resync_republishes_everything(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app.set_state.reset_mock()
    app._cb_plugin_started("plugin_started", {}, {})
    published = {c.args[0] for c in app.set_state.call_args_list}
    assert "sensor.coffee_state" in published and "binary_sensor.coffee_armed" in published


def test_adapter_counter_update_publishes(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app.set_state.reset_mock()
    app._cb_counter("counter.coffee_brews_since_descale", "state", "99", "100", {})
    published = {c.args[0]: c.kwargs["state"] for c in app.set_state.call_args_list}
    assert published["binary_sensor.coffee_maintenance_due"] == "on"


def test_adapter_stale_timer_callback_keeps_the_new_handle(monkeypatch, tmp_path):
    app = make_adapter(monkeypatch, tmp_path, HEALTHY)
    app._cb_button("input_button.coffee_arm", "state", "a", "b", {"kind": "arm"})
    handle, token = app._handles["arming_expiry"]
    app._on_timer({"timer_name": "arming_expiry", "token": token - 1000})
    assert app._handles["arming_expiry"] == (handle, token)
    assert app.core.state == cs.ARMED


def test_power_drawn_while_plug_reports_off_escalates():
    """Stuck relay: the switch says off but the brewer still draws power."""
    sim = drained()
    sim.plug_follows = False
    sim.power(BREW_W)  # switch already reports off
    assert sim.plug_commands[-1] == "off"
    assert sim.core.shutdown is not None
    sim.advance(60)  # retries exhausted with power still high
    assert sim.core.fault_reason == "shutdown_unconfirmed"
    assert sim.notifications[-1]["level"] == "critical"
