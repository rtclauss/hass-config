"""Smart coffee station: one authoritative state machine for a Moccamaster on a
power-monitoring smart plug, armed by an IKEA RODRET remote and brewed when the
resident actually gets out of bed in the morning.

Design (see docs/coffee_station.md for the full write-up):

* ``CoffeeCore`` is a pure, deterministic state machine. It never talks to Home
  Assistant: every input is a method call carrying an explicit timestamp, and
  every output is an *effect* tuple appended to ``core.effects``. That is what
  the tests drive with simulated clocks and power traces.
* ``CoffeeStation`` is the thin AppDaemon adapter. It turns HA state changes,
  events and timers into core calls (under one lock) and executes the effects
  (service calls, timers, notifications, published entities).

Safety posture (this switches a ~1.4 kW heating appliance):

* Arming is a one-time authorization. It is never persisted: any AppDaemon or
  Home Assistant restart disarms, and a plug found energized at start-up is
  switched off.
* Turning the plug on is never taken as proof of brewing; heating is confirmed
  from the power sensor, and every energized period is bounded by a startup
  timeout, a telemetry-staleness check and a maximum energized time.
* Every shutdown is confirmed (switch reports off AND power falls to idle) and
  escalates to a critical notification when it cannot be confirmed.
* The OFF button / stop control stops the plug in every state. An independent
  Home Assistant automation (packages/coffee.yaml) provides the same stop path
  and a max-on watchdog without depending on AppDaemon.
* Software timers here are defense in depth, not hardware safety devices; the
  appliance's own thermostat/thermal fuse remain the primary protection.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

try:  # AppDaemon provides hassapi; unit tests stub it or run without it.
    import hassapi as hass

    _HassBase = hass.Hass
except Exception:  # pragma: no cover - exercised only outside AppDaemon
    _HassBase = object


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coffee_station_state.json")

# ---------------------------------------------------------------------------
# States and transitions
# ---------------------------------------------------------------------------

IDLE = "idle"
ARMED = "armed"
WAITING = "waiting_for_wakeup"
STARTING = "starting"
BREWING = "brewing"
DRAINING = "draining"
READY = "ready"
CANCELLED = "cancelled"
FAULT = "fault"
UNAVAILABLE = "unavailable"

ALL_STATES = (IDLE, ARMED, WAITING, STARTING, BREWING, DRAINING, READY, CANCELLED, FAULT, UNAVAILABLE)
ARMED_STATES = (ARMED, WAITING)
ACTIVE_STATES = (STARTING, BREWING, DRAINING)
RESTING_STATES = (IDLE, READY, CANCELLED)

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    IDLE: frozenset({ARMED, STARTING, FAULT, UNAVAILABLE}),
    ARMED: frozenset({WAITING, STARTING, CANCELLED, FAULT, UNAVAILABLE}),
    WAITING: frozenset({ARMED, STARTING, CANCELLED, FAULT, UNAVAILABLE}),
    STARTING: frozenset({BREWING, CANCELLED, FAULT}),
    BREWING: frozenset({DRAINING, CANCELLED, FAULT}),
    DRAINING: frozenset({READY, CANCELLED, FAULT}),
    READY: frozenset({IDLE, ARMED, STARTING, FAULT, UNAVAILABLE}),
    CANCELLED: frozenset({IDLE, ARMED, STARTING, FAULT, UNAVAILABLE}),
    # A fault latches until it is explicitly acknowledged.
    FAULT: frozenset({IDLE}),
    UNAVAILABLE: frozenset({IDLE, FAULT}),
}

# Timers owned by a state are cancelled on exit (unless the next state owns
# them too). ``shutdown_confirm`` is deliberately state-independent.
STATE_TIMERS: dict[str, frozenset[str]] = {
    IDLE: frozenset(),
    ARMED: frozenset({"arming_expiry"}),
    WAITING: frozenset({"arming_expiry", "vacancy"}),
    STARTING: frozenset({"startup", "heat_confirm", "max_energized"}),
    BREWING: frozenset({"completion", "max_energized"}),
    DRAINING: frozenset({"drainage", "keep_warm", "max_energized"}),
    READY: frozenset({"hold", "keep_warm", "max_energized"}),
    CANCELLED: frozenset({"hold"}),
    FAULT: frozenset(),
    UNAVAILABLE: frozenset(),
}

# Fault reasons that indicate the appliance/plug itself misbehaved (as opposed
# to e.g. a short brew from an empty reservoir).
SAFETY_FAULTS = frozenset(
    {
        "shutdown_unconfirmed",
        "excessive_runtime",
        "stale_telemetry",
        "telemetry_lost",
        "plug_unavailable_during_brew",
        "energized_after_power_restore",
    }
)

# Material Design Icons per state, so the station's icon shows what the
# coffee maker is doing at a glance (dashboard tiles, more-info, HomeKit).
STATE_ICONS: dict[str, str] = {
    IDLE: "mdi:coffee-maker-outline",
    ARMED: "mdi:coffee-maker-check",
    WAITING: "mdi:coffee-maker-check-outline",
    STARTING: "mdi:power-plug",
    BREWING: "mdi:coffee-maker",
    DRAINING: "mdi:water-outline",
    READY: "mdi:coffee",
    CANCELLED: "mdi:coffee-off-outline",
    FAULT: "mdi:alert-octagon",
    UNAVAILABLE: "mdi:coffee-off",
}

# (icon when on, icon when off) for the published binary sensors.
BINARY_ICONS: dict[str, tuple[str, str]] = {
    "binary_sensor.coffee_armed": ("mdi:coffee-maker-check", "mdi:coffee-maker-outline"),
    "binary_sensor.coffee_brewing": ("mdi:coffee-maker", "mdi:coffee-maker-outline"),
    "binary_sensor.coffee_ready": ("mdi:coffee", "mdi:coffee-outline"),
    "binary_sensor.coffee_station_available": ("mdi:coffee-maker", "mdi:coffee-off"),
    "binary_sensor.coffee_maintenance_due": ("mdi:water-alert", "mdi:water-check"),
}

# Power above this while the switch reports OFF means a possible stuck relay
# (same threshold as the YAML watchdog in packages/coffee.yaml).
STUCK_RELAY_W = 50.0

TAG_LIFECYCLE = "coffee_station"
TAG_FAULT = "coffee_station_fault"
TAG_MAINTENANCE = "coffee_station_maintenance"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROFILES: dict[str, dict[str, float]] = {
    # KBGT and other thermal-carafe brewers: the element switches itself off
    # when the reservoir is empty and there is no warming plate, so power falls
    # to (near) zero at the end of heating.
    "thermal_carafe": {
        "heating_threshold_w": 500.0,
        "completion_threshold_w": 5.0,
        "keep_warm_s": 0.0,
    },
    # Glass-carafe brewers with a warming plate: after heating the plate keeps
    # cycling at a much lower wattage, so "complete" means "below the heating
    # band", not "near zero". keep_warm_s > 0 leaves the plate powered for that
    # long after completion (the brewer's own plate auto-off still applies).
    "glass_hotplate": {
        "heating_threshold_w": 500.0,
        "completion_threshold_w": 150.0,
        "keep_warm_s": 0.0,
    },
}

DEFAULTS: dict[str, Any] = {
    "profile": "thermal_carafe",
    "time_zone": "America/Chicago",
    "weekday_window": ["05:00", "11:00"],
    "weekend_window": ["05:00", "11:00"],
    "weekend_days": [5, 6],  # Monday=0
    "vacancy_debounce_s": 300,
    "min_prior_occupancy_s": 3600,
    "max_arming_s": 18 * 3600,
    "max_auto_brews": 1,
    "idle_threshold_w": 5.0,
    "startup_timeout_s": 30,
    "heating_confirm_s": 10,
    "completion_debounce_s": 30,
    "drainage_s": 90,
    "max_energized_s": 12 * 60,
    "short_brew_s": 90,
    "typical_heating_s": 300,
    "telemetry_stale_s": 120,
    "liveness_max_age_s": 1800,
    "shutdown_confirm_s": 15,
    "shutdown_retries": 3,
    "ready_hold_s": 3600,
    "cancelled_hold_s": 60,
    "remote_debounce_s": 1.0,
    "long_press_latch_s": 20,
    "stop_brew_when_away": True,
    "manual_activation_policy": "shutoff",  # or "supervise_if_home" (opt-in)
    "enforce_power_on_behavior": True,
    "descale_brews": 100,
    "descale_days": 90,
    "tick_s": 30,
}


def _parse_hhmm(value: str) -> dtime:
    hours, minutes = str(value).split(":")[:2]
    return dtime(int(hours), int(minutes))


@dataclass
class CoffeeConfig:
    profile: str = DEFAULTS["profile"]
    time_zone: str = DEFAULTS["time_zone"]
    weekday_window: tuple[dtime, dtime] = (dtime(5, 0), dtime(11, 0))
    weekend_window: tuple[dtime, dtime] = (dtime(5, 0), dtime(11, 0))
    weekend_days: tuple[int, ...] = (5, 6)
    vacancy_debounce_s: float = 300.0
    min_prior_occupancy_s: float = 3600.0
    max_arming_s: float = 18 * 3600
    max_auto_brews: int = 1
    heating_threshold_w: float = 500.0
    completion_threshold_w: float = 5.0
    idle_threshold_w: float = 5.0
    keep_warm_s: float = 0.0
    startup_timeout_s: float = 30
    heating_confirm_s: float = 10
    completion_debounce_s: float = 30
    drainage_s: float = 90
    max_energized_s: float = 720
    short_brew_s: float = 90
    typical_heating_s: float = 300
    telemetry_stale_s: float = 120
    liveness_max_age_s: float = 1800
    has_liveness: bool = False
    has_power_on_behavior: bool = False
    shutdown_confirm_s: float = 15
    shutdown_retries: int = 3
    ready_hold_s: float = 3600
    cancelled_hold_s: float = 60
    remote_debounce_s: float = 1.0
    long_press_latch_s: float = 20
    stop_brew_when_away: bool = True
    manual_activation_policy: str = "shutoff"
    enforce_power_on_behavior: bool = True
    descale_brews: int = 100
    descale_days: float = 90
    tick_s: float = 30

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.time_zone)

    @classmethod
    def from_args(cls, args: dict[str, Any] | None) -> "CoffeeConfig":
        args = args or {}
        merged = {**DEFAULTS, **{k: v for k, v in args.items() if v is not None}}
        profile_name = merged["profile"]
        if profile_name not in PROFILES:
            raise ValueError(f"unknown coffee maker profile {profile_name!r}; choose one of {sorted(PROFILES)}")
        # Profile values first, then any explicit per-key override from args.
        for key, value in PROFILES[profile_name].items():
            merged[key] = args.get(key, value)
        cfg = cls()
        skip = {"weekday_window", "weekend_window", "weekend_days", "has_liveness", "has_power_on_behavior"}
        int_fields = {"max_auto_brews", "shutdown_retries", "descale_brews"}
        for name in cls.__dataclass_fields__:
            if name in skip or name not in merged:
                continue
            current = getattr(cfg, name)
            raw = merged[name]
            if isinstance(current, bool):
                value: Any = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
            elif name in int_fields:
                value = int(raw)
            elif isinstance(current, (int, float)):
                value = float(raw)
            else:
                value = str(raw)
            setattr(cfg, name, value)
        cfg.weekday_window = tuple(_parse_hhmm(v) for v in merged["weekday_window"])  # type: ignore[assignment]
        cfg.weekend_window = tuple(_parse_hhmm(v) for v in merged["weekend_window"])  # type: ignore[assignment]
        cfg.weekend_days = tuple(int(d) for d in merged["weekend_days"])
        cfg.has_liveness = bool(args.get("liveness_entities"))
        cfg.has_power_on_behavior = bool(args.get("power_on_behavior_entity"))
        cfg.validate()
        return cfg

    def validate(self) -> None:
        problems = []
        for start, end in (self.weekday_window, self.weekend_window):
            if not start < end:
                problems.append("morning window start must be before its end")
        if not self.idle_threshold_w < self.heating_threshold_w:
            problems.append("idle_threshold_w must be below heating_threshold_w")
        if not self.completion_threshold_w < self.heating_threshold_w:
            problems.append("completion_threshold_w must be below heating_threshold_w")
        if self.manual_activation_policy not in ("supervise_if_home", "shutoff"):
            problems.append("manual_activation_policy must be supervise_if_home or shutoff")
        if self.max_auto_brews < 1:
            problems.append("max_auto_brews must be at least 1")
        if self.max_energized_s <= self.startup_timeout_s:
            problems.append("max_energized_s must exceed startup_timeout_s")
        if self.keep_warm_s and self.keep_warm_s >= self.ready_hold_s:
            problems.append("keep_warm_s must be shorter than ready_hold_s")
        if problems:
            raise ValueError("; ".join(problems))


@dataclass
class Window:
    start: datetime
    end: datetime

    def contains(self, when: datetime) -> bool:
        return self.start <= when < self.end


@dataclass
class Brew:
    source: str
    started_at: datetime
    heat_above_since: datetime | None = None
    heating_started_at: datetime | None = None
    below_since: datetime | None = None
    heating_ended_at: datetime | None = None
    peak_power_w: float = 0.0
    energy_wh: float = 0.0
    energy_start_kwh: float | None = None
    interruptions: int = 0
    drained: bool = False
    off_confirmed: bool = False
    _last_power: float | None = None
    _last_power_at: datetime | None = None

    def sample(self, watts: float | None, now: datetime) -> None:
        if self._last_power is not None and self._last_power_at is not None:
            hours = max(0.0, (now - self._last_power_at).total_seconds()) / 3600.0
            self.energy_wh += self._last_power * hours
        self._last_power = watts
        self._last_power_at = now
        if watts is not None:
            self.peak_power_w = max(self.peak_power_w, watts)


# ---------------------------------------------------------------------------
# Pure state machine
# ---------------------------------------------------------------------------


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        raise ValueError("CoffeeCore requires timezone-aware datetimes")
    return when.astimezone(timezone.utc)


class CoffeeCore:
    """Authoritative coffee-station state machine. Not thread-safe by itself:
    the adapter serializes every call behind one lock."""

    def __init__(self, cfg: CoffeeConfig) -> None:
        self.cfg = cfg
        self.effects: list[tuple] = []
        self.state = UNAVAILABLE
        self.started = False
        self._timers: dict[str, int] = {}
        self._token = 0
        # Inputs (None = unknown / unavailable).
        self.plug: str | None = None
        self.power: float | None = None
        self.energy_kwh: float | None = None
        self.telemetry_at: datetime | None = None
        self.bed: bool | None = None
        self.bed_health_ok = True
        self.bed_valid = False
        self.session_start: datetime | None = None
        self.vacancy_since: datetime | None = None
        self.home: bool | None = None
        self.vacation = False
        self.power_on_behavior: str | None = None
        self.remote_available = True
        # Arming.
        self.armed_at: datetime | None = None
        self.armed_until: datetime | None = None
        self.window: Window | None = None
        self.arming_source: str | None = None
        self.auto_brews_used = 0
        # Brewing.
        self.brew: Brew | None = None
        self.last_brew: dict[str, Any] | None = None
        self.shutdown: dict[str, Any] | None = None
        self.expect_on_until: datetime | None = None
        # Diagnostics.
        self.fault_reason: str | None = None
        self.last_fault_reason: str | None = None
        self.last_transition: datetime | None = None
        self.transition_reason: str | None = None
        self.last_ignored: str | None = None
        self.last_successful_brew: datetime | None = None
        self.brew_trigger_source: str | None = None
        # Remote debounce/latch.
        self._remote_last: dict[str, datetime] = {}
        self._latched_until: dict[str, datetime] = {}
        # Maintenance.
        self.brews_since_descale = 0
        self.last_descale: datetime | None = None
        self.maintenance_notified = False

    # ------------------------------------------------------------------ utils

    def _emit(self, *effect: Any) -> None:
        self.effects.append(tuple(effect))

    def drain(self) -> list[tuple]:
        effects, self.effects = self.effects, []
        return effects

    def _log(self, message: str, level: str = "INFO") -> None:
        self._emit("log", level, message)

    def _schedule(self, name: str, delay_s: float) -> None:
        self._token += 1
        self._timers[name] = self._token
        self._emit("timer", name, max(0.0, float(delay_s)), self._token)

    def _cancel(self, name: str) -> None:
        if self._timers.pop(name, None) is not None:
            self._emit("cancel_timer", name)

    def timer_active(self, name: str) -> bool:
        return name in self._timers

    def _local(self, when: datetime) -> datetime:
        return when.astimezone(self.cfg.tz)

    def telemetry_age(self, now: datetime) -> float | None:
        if self.telemetry_at is None:
            return None
        return max(0.0, (now - self.telemetry_at).total_seconds())

    # --------------------------------------------------------------- windows

    def window_for(self, day: date) -> Window:
        start_t, end_t = self.cfg.weekend_window if day.weekday() in self.cfg.weekend_days else self.cfg.weekday_window
        tz = self.cfg.tz
        start = datetime.combine(day, start_t, tzinfo=tz).astimezone(timezone.utc)
        end = datetime.combine(day, end_t, tzinfo=tz).astimezone(timezone.utc)
        return Window(start, end)

    def next_window(self, now: datetime) -> Window:
        """The next morning window that has not started yet. Arming during a
        window therefore targets tomorrow; use brew-now for an immediate pot."""
        day = self._local(now).date()
        for offset in range(0, 8):
            window = self.window_for(day + timedelta(days=offset))
            if window.start > now:
                return window
        raise RuntimeError("no morning window in the next week")  # pragma: no cover

    # ------------------------------------------------------------ transitions

    def _transition(self, new: str, reason: str, now: datetime) -> bool:
        old = self.state
        if new == old:
            return False
        if new not in VALID_TRANSITIONS[old]:
            self._log(f"refused invalid transition {old} -> {new} ({reason})", "WARNING")
            return False
        for name in STATE_TIMERS[old] - STATE_TIMERS[new]:
            self._cancel(name)
        self.state = new
        self.last_transition = now
        self.transition_reason = reason
        self._log(f"{old} -> {new}: {reason}")
        self._on_enter(old, new, reason, now)
        self._persist()
        return True

    def _on_enter(self, old: str, new: str, reason: str, now: datetime) -> None:
        if new in (IDLE, CANCELLED, UNAVAILABLE, FAULT) or new in ACTIVE_STATES:
            if old in ARMED_STATES and new not in ARMED_STATES:
                self._clear_arming()
        if new == CANCELLED:
            self._schedule("hold", self.cfg.cancelled_hold_s)
        elif new == READY:
            self._schedule("hold", self.cfg.ready_hold_s)
        elif new == FAULT:
            self.fault_reason = reason
            self.last_fault_reason = reason
            self.request_shutdown(f"fault: {reason}", now)
        elif new == IDLE:
            self.fault_reason = None

    def _clear_arming(self) -> None:
        self.armed_at = None
        self.armed_until = None
        self.window = None
        self.arming_source = None

    def _persist(self) -> None:
        self._emit(
            "persist",
            {
                "state": self.state,
                "armed": self.state in ARMED_STATES,
                "active": self.state in ACTIVE_STATES,
                "fault_reason": self.fault_reason if self.state == FAULT else None,
                "maintenance_notified": self.maintenance_notified,
            },
        )

    # -------------------------------------------------------------- notifier

    def _notify(self, kind: str, title: str, message: str, *, tag: str = TAG_LIFECYCLE,
                level: str = "active", actions: Iterable[str] = ()) -> None:
        self._emit("notify", {"kind": kind, "title": title, "message": message, "tag": tag,
                              "level": level, "actions": list(actions)})

    def _fault(self, reason: str, message: str, now: datetime, level: str = "time-sensitive") -> None:
        was_active = self.state in ACTIVE_STATES
        if self.state == FAULT:
            # Already latched: keep the first reason, but record and surface
            # an escalation (e.g. shutdown_unconfirmed on top of a fault).
            self.last_fault_reason = reason
            if reason in SAFETY_FAULTS:
                self.fault_reason = reason
            self.request_shutdown(f"fault: {reason}", now)
        else:
            self._transition(FAULT, reason, now)
        if was_active:
            self._emit("counter", "failed", "increment")
            self._finish_brew_record(now, success=False, reason=reason)
        self._notify("fault", "Coffee maker fault", message, tag=TAG_FAULT, level=level,
                     actions=("COFFEE_STOP",))

    # ------------------------------------------------------------- lifecycle

    def on_start(self, now: datetime, snapshot: dict[str, Any], previous: dict[str, Any] | None) -> None:
        """App initialization (AppDaemon start/reload or HA reconnect)."""
        now = _utc(now)
        self.started = True
        self.state = IDLE
        self._timers.clear()
        self.brew = None
        self.shutdown = None
        self.expect_on_until = None
        self._clear_arming()
        self.fault_reason = None
        self._apply_snapshot(snapshot, now)
        previous = previous or {}
        self.maintenance_notified = bool(previous.get("maintenance_notified", False))
        if previous.get("active"):
            # A brew was cut short by the restart: count it as interrupted.
            self._emit("counter", "failed", "increment")
        if previous.get("state") == FAULT:
            # A fault latches until acknowledged, across restarts too.
            self.state = FAULT
            self.fault_reason = previous.get("fault_reason") or "unacknowledged fault before restart"
            self.last_fault_reason = self.fault_reason
        if previous.get("armed") or previous.get("active"):
            self._notify(
                "restart_disarmed",
                "Coffee maker disarmed",
                "The coffee station restarted, so the arming was cleared. Arm it again if the "
                "brewer is still prepared.",
                level="passive",
            )
        if self.plug == "on":
            self._log("plug was energized at start-up; switching it off", "WARNING")
            self.request_shutdown("start-up safety", now)
            self._notify(
                "startup_shutoff",
                "Coffee maker switched off",
                "The coffee maker plug was on when the coffee station started, so it was switched "
                "off. Automatic brewing never resumes after a restart.",
                tag=TAG_FAULT,
                level="time-sensitive",
            )
        self._enforce_power_on_behavior()
        self.transition_reason = "start-up"
        self.last_transition = now
        self._recover_or_degrade(now)
        self._persist()

    def _apply_snapshot(self, snapshot: dict[str, Any], now: datetime) -> None:
        self.plug = snapshot.get("plug")
        self.power = snapshot.get("power")
        self.energy_kwh = snapshot.get("energy_kwh")
        self.telemetry_at = snapshot.get("telemetry_at")
        self.bed = snapshot.get("bed")
        self.bed_valid = self.bed is not None
        self.bed_health_ok = snapshot.get("bed_health_ok", True)
        bed_since = snapshot.get("bed_since")
        if self.bed is True:
            self.session_start = bed_since or now
            self.vacancy_since = None
        elif self.bed is False:
            self.session_start = None
            self.vacancy_since = bed_since or now
        self.home = snapshot.get("home")
        self.vacation = bool(snapshot.get("vacation", False))
        self.power_on_behavior = snapshot.get("power_on_behavior")
        self.remote_available = snapshot.get("remote_available", True)
        self.brews_since_descale = int(snapshot.get("brews_since_descale") or 0)
        self.last_descale = snapshot.get("last_descale")

    def _enforce_power_on_behavior(self) -> None:
        if (self.cfg.has_power_on_behavior and self.cfg.enforce_power_on_behavior
                and self.power_on_behavior not in (None, "off")):
            self._emit("set_power_on_behavior", "off")

    # ------------------------------------------------------------ availability

    def station_issues(self, now: datetime, *, hard_only: bool = False) -> list[str]:
        """Problems that make the station unable to brew safely.

        *Hard* issues (plug or power sensor unavailable, power-on behavior
        known and not OFF) cancel an arming. *Soft* issues (quiet telemetry,
        power-on behavior momentarily unknown) only block arming and the start
        of a brew: Matter reports on change, so a quiet plug overnight must not
        silently cancel tomorrow's coffee.
        """
        issues = []
        if self.plug is None:
            issues.append("plug unavailable")
        if self.power is None:
            issues.append("power telemetry unavailable")
        if (self.cfg.has_power_on_behavior and self.power_on_behavior is not None
                and self.power_on_behavior != "off"):
            issues.append(f"plug power-on behavior is {self.power_on_behavior!r}, not 'off'")
        if hard_only:
            return issues
        if self.cfg.has_liveness:
            age = self.telemetry_age(now)
            if age is None or age > self.cfg.liveness_max_age_s:
                issues.append("plug telemetry stale")
        if self.cfg.has_power_on_behavior and self.power_on_behavior is None:
            issues.append("plug power-on behavior unknown")
        return issues

    def _recover_or_degrade(self, now: datetime) -> None:
        issues = self.station_issues(now)
        if self.state == UNAVAILABLE and not issues:
            self._transition(IDLE, "station available", now)
        elif issues and self.state in RESTING_STATES:
            self._transition(UNAVAILABLE, "; ".join(issues), now)
        elif self.state in ARMED_STATES:
            hard = self.station_issues(now, hard_only=True)
            if hard and self._transition(UNAVAILABLE, "; ".join(hard), now):
                self._notify("disarmed_unavailable", "Coffee maker disarmed",
                             f"Arming was cancelled because the station is unavailable: {'; '.join(hard)}.",
                             level="active")

    # ---------------------------------------------------------------- requests

    def request(self, kind: str, source: str, now: datetime) -> None:
        now = _utc(now)
        handler = {
            "arm": self._request_arm,
            "brew_now": self._request_brew_now,
            "stop": self._request_stop,
            "acknowledge": self._request_acknowledge,
            "disarm": self._request_disarm,
            "reset_maintenance": self._request_reset_maintenance,
        }.get(kind)
        if handler is None:
            self._log(f"ignored unknown request {kind!r}", "WARNING")
            return
        handler(source, now)

    def _refuse(self, kind: str, message: str, level: str = "active") -> None:
        self.last_ignored = message
        self._log(f"refused: {message}")
        self._notify(kind, "Coffee maker not changed", message, level=level)

    def _request_arm(self, source: str, now: datetime) -> None:
        if self.state in ARMED_STATES:
            self.last_ignored = "already armed"
            return  # idempotent: duplicate arm presses do nothing
        if self.state == FAULT:
            return self._refuse("arm_refused", f"Acknowledge the fault first ({self.fault_reason}): hold OFF on the remote.")
        if self.state in ACTIVE_STATES:
            return self._refuse("arm_refused", "A brew is already in progress.")
        issues = self.station_issues(now)
        if issues:
            return self._refuse("arm_refused", f"The coffee station is unavailable: {'; '.join(issues)}.")
        if self.plug != "off" or (self.power is not None and self.power > self.cfg.idle_threshold_w):
            return self._refuse("arm_refused", "The coffee maker plug is already on. Switch it off, then arm again.")
        if self.home is not True:
            return self._refuse("arm_refused", "Arming needs you to be home.")
        if self.vacation:
            return self._refuse("arm_refused", "Arming is disabled while vacation or trip mode is on.")
        window = self.next_window(now)
        if (window.start - now).total_seconds() >= self.cfg.max_arming_s:
            earliest = self._local(window.start - timedelta(seconds=self.cfg.max_arming_s))
            return self._refuse(
                "arm_refused",
                f"Too early to arm for tomorrow's window. Arm after {earliest:%H:%M}.",
            )
        self.armed_at = now
        self.window = window
        self.armed_until = min(window.end, now + timedelta(seconds=self.cfg.max_arming_s))
        self.arming_source = source
        self.auto_brews_used = 0
        if self._transition(ARMED, f"armed by {source}", now):
            self._schedule("arming_expiry", (self.armed_until - now).total_seconds())
            self._emit("feedback", "armed")
            start_l, end_l = self._local(window.start), self._local(window.end)
            self._notify(
                "armed",
                "Coffee maker armed",
                f"Coffee will brew once you are up between {start_l:%a %H:%M} and {end_l:%H:%M}. "
                "You confirmed water, filter, grounds, basket, empty carafe and the brewer switch.",
                level="passive",
                actions=("COFFEE_DISARM",),
            )

    def _request_disarm(self, source: str, now: datetime) -> None:
        if self.state in ARMED_STATES:
            self._cancel_arming(f"disarmed by {source}", now)

    def _cancel_arming(self, reason: str, now: datetime, level: str = "passive") -> None:
        if self._transition(CANCELLED, reason, now):
            self._notify("cancelled", "Coffee maker disarmed", f"Arming cancelled: {reason}.", level=level)

    def _request_brew_now(self, source: str, now: datetime) -> None:
        if self.state not in ARMED_STATES:
            if self.state in ACTIVE_STATES:
                self.last_ignored = "brew already in progress"
                return
            return self._refuse("brew_refused",
                                "Arm the coffee maker first (press ON) to confirm it is prepared.")
        problem = self._brew_blocker(now)
        if problem:
            return self._refuse("brew_refused", f"Not brewing: {problem}.")
        self._start_brew(source, now, automatic=False)

    def _request_stop(self, source: str, now: datetime) -> None:
        # Stop works in every state: always command the plug off, even when we
        # believe it already is (our view of the plug could be stale). OFF is
        # idempotent and confirmed immediately when the plug already reports off.
        self.request_shutdown(f"stop by {source}", now)
        if self.state in ARMED_STATES:
            self._cancel_arming(f"disarmed by {source}", now)
        elif self.state in (STARTING, BREWING):
            self._emit("counter", "failed", "increment")
            self._finish_brew_record(now, success=False, reason=f"stopped by {source}")
            if self._transition(CANCELLED, f"stopped by {source}", now):
                self._notify("stopped", "Coffee stopped", f"Brewing was stopped by {source}.", level="passive")
        elif self.state in (READY, CANCELLED):
            self._transition(IDLE, f"dismissed by {source}", now)
        # DRAINING: the plug is already being switched off; drainage continues.
        # FAULT / UNAVAILABLE: the shutdown request above is all that is needed.

    def _request_acknowledge(self, source: str, now: datetime) -> None:
        self._request_stop(source, now)
        if self.state != FAULT:
            return
        if self.shutdown is not None or self.plug != "off":
            return self._refuse("ack_refused",
                                "The plug is not confirmed off yet, so the fault stays latched.",
                                level="time-sensitive")
        reason = self.fault_reason
        self._transition(IDLE, f"fault {reason} acknowledged by {source}", now)
        self._emit("clear_notification", TAG_FAULT)
        self._recover_or_degrade(now)

    def _request_reset_maintenance(self, source: str, now: datetime) -> None:
        self.brews_since_descale = 0
        self.last_descale = now
        self.maintenance_notified = False
        self._emit("counter", "since_descale", "reset")
        self._emit("set_last_descale", now)
        self._emit("clear_notification", TAG_MAINTENANCE)
        self._persist()

    # ---------------------------------------------------------------- brewing

    def _brew_blocker(self, now: datetime) -> str | None:
        issues = self.station_issues(now)
        if issues:
            return "; ".join(issues)
        if self.brew is not None or self.state in ACTIVE_STATES:
            return "a brew is already in progress"
        if self.shutdown is not None:
            return "a previous shutdown is still being confirmed"
        if self.plug != "off":
            return "the plug is already on"
        if self.power is not None and self.power > self.cfg.idle_threshold_w:
            return f"the plug already draws {self.power:.0f} W"
        if self.home is not True:
            return "you are not home"
        if self.vacation:
            return "vacation or trip mode is on"
        age = self.telemetry_age(now)
        if self.cfg.has_liveness and (age is None or age > self.cfg.liveness_max_age_s):
            return "plug telemetry is stale"
        return None

    def _start_brew(self, source: str, now: datetime, *, automatic: bool, plug_already_on: bool = False) -> None:
        self.brew = Brew(source=source, started_at=now, energy_start_kwh=self.energy_kwh)
        self.brew.sample(self.power, now)
        self.brew_trigger_source = source
        if not self._transition(STARTING, f"brew started by {source}", now):
            self.brew = None
            return
        if automatic:
            self.auto_brews_used += 1
        if not plug_already_on:
            self.expect_on_until = now + timedelta(seconds=self.cfg.startup_timeout_s + 5)
            self._emit("plug", "on")
        self._schedule("startup", self.cfg.startup_timeout_s)
        self._schedule("max_energized", self.cfg.max_energized_s)
        if self.power is not None and self.power >= self.cfg.heating_threshold_w:
            self.brew.heat_above_since = now
            self._schedule("heat_confirm", self.cfg.heating_confirm_s)
        self._notify("brewing", "Coffee brewing", f"Brewing started ({source}).",
                     level="passive", actions=("COFFEE_STOP",))

    def _finish_brew_record(self, now: datetime, *, success: bool, reason: str) -> None:
        brew = self.brew
        if brew is None:
            return
        brew.sample(self.power, now)
        heating_end = brew.heating_ended_at or now
        heating_s = ((heating_end - brew.heating_started_at).total_seconds()
                     if brew.heating_started_at else 0.0)
        energy_wh = brew.energy_wh
        if brew.energy_start_kwh is not None and self.energy_kwh is not None:
            delta = (self.energy_kwh - brew.energy_start_kwh) * 1000.0
            if delta > 0:
                energy_wh = delta
        self.last_brew = {
            "success": success,
            "reason": reason,
            "source": brew.source,
            "started_at": brew.started_at,
            "heating_s": round(heating_s, 1),
            "energy_wh": round(energy_wh, 1),
            "integrated_energy_wh": round(brew.energy_wh, 1),
            "peak_power_w": round(brew.peak_power_w, 1),
            "interruptions": brew.interruptions,
        }
        if success:
            self._emit("record_brew", dict(self.last_brew, finished_at=now))
        self.brew = None

    def request_shutdown(self, reason: str, now: datetime) -> None:
        now = _utc(now)
        self.expect_on_until = None
        if self.shutdown is None:
            self.shutdown = {"reason": reason, "attempts": 1, "requested_at": now}
        else:
            self.shutdown["reason"] = reason
        self._emit("plug", "off")
        if not self.timer_active("shutdown_confirm"):
            self._schedule("shutdown_confirm", self.cfg.shutdown_confirm_s)
        self._check_shutdown(now)

    def _plug_confirmed_off(self) -> bool:
        # The switch must report off. Power must be idle when it is reported;
        # if the power sensor itself is unavailable, the switch report alone
        # confirms (logged as such) - the alternative would be an unresolvable
        # critical alert for a plug that says it is off.
        return self.plug == "off" and (self.power is None or self.power <= self.cfg.idle_threshold_w)

    def _check_shutdown(self, now: datetime) -> None:
        if self.shutdown is None or not self._plug_confirmed_off():
            return
        how = "switch off, power unknown" if self.power is None else f"switch off, {self.power:.0f} W"
        self._log(f"shutdown confirmed ({self.shutdown['reason']}; {how})")
        was_unconfirmed = self.shutdown.get("alerted_at") is not None
        self.shutdown = None
        self._cancel("shutdown_confirm")
        self._cancel("max_energized")
        if was_unconfirmed:
            self._notify("shutdown_confirmed", "Coffee maker confirmed off",
                         "The coffee maker plug now reports off. Acknowledge the fault after checking it.",
                         tag=TAG_FAULT, level="time-sensitive")
        if self.brew is not None:
            self.brew.off_confirmed = True
        if self.state == DRAINING and self.brew is not None and self.brew.drained:
            self._complete(now)

    def _complete(self, now: datetime) -> None:
        self._finish_brew_record(now, success=True, reason="brew complete")
        self.last_successful_brew = now
        self.brews_since_descale += 1
        self._emit("counter", "total", "increment")
        self._emit("counter", "since_descale", "increment")
        self._transition(READY, "brew complete", now)
        self._emit("feedback", "ready")
        self._notify("ready", "Coffee is ready", "Your coffee has finished brewing.", level="active")
        self._check_maintenance(now)

    def _check_maintenance(self, now: datetime) -> None:
        if self.maintenance_due(now) and not self.maintenance_notified:
            self.maintenance_notified = True
            self._notify("maintenance", "Descale the coffee maker",
                         f"{self.brews_since_descale} brews since the last descale. Descale it, then "
                         "press Reset maintenance on the Coffee dashboard.",
                         tag=TAG_MAINTENANCE, level="passive")
            self._persist()

    def maintenance_due(self, now: datetime) -> bool:
        if self.brews_since_descale >= self.cfg.descale_brews:
            return True
        if self.last_descale is not None:
            return (now - self.last_descale).total_seconds() >= self.cfg.descale_days * 86400
        return False

    # ------------------------------------------------------------------ inputs

    def on_remote(self, action: str | None, now: datetime) -> None:
        now = _utc(now)
        if not action:
            return
        if action == "brightness_stop":
            self._latched_until.clear()
            return
        last = self._remote_last.get(action)
        self._remote_last[action] = now
        if last is not None and (now - last).total_seconds() < self.cfg.remote_debounce_s:
            self.last_ignored = f"duplicate remote action {action}"
            return
        if action in ("brightness_move_up", "brightness_move_down"):
            latched = self._latched_until.get(action)
            if latched is not None and now < latched:
                self.last_ignored = f"long-press repeat {action}"
                return
            self._latched_until[action] = now + timedelta(seconds=self.cfg.long_press_latch_s)
        mapping = {
            "on": "arm",
            "brightness_move_up": "brew_now",
            "off": "stop",
            "brightness_move_down": "acknowledge",
        }
        kind = mapping.get(action)
        if kind is None:
            self.last_ignored = f"unmapped remote action {action}"
            return
        self.request(kind, "remote", now)

    def on_bed(self, occupied: bool | None, now: datetime) -> None:
        """Bed occupancy. ``self.bed`` keeps the last *valid* value so a brief
        sensor dropout neither fabricates a transition nor resets the sleep
        session; ``self.bed_valid`` says whether the current reading is usable."""
        now = _utc(now)
        previous = self.bed
        if occupied is None:
            self.bed_valid = False
            if self.state == WAITING:
                self._transition(ARMED, "bed occupancy data invalid", now)
            return
        self.bed_valid = True
        if occupied == previous:
            return  # duplicate update, or recovery to the same value
        self.bed = occupied
        if occupied:
            gap = (now - self.vacancy_since).total_seconds() if self.vacancy_since else None
            # A short trip out of bed (< the vacancy debounce) does not start a
            # new sleep session; anything longer, or unknown history, does.
            if self.session_start is None or gap is None or gap >= self.cfg.vacancy_debounce_s:
                self.session_start = now
            self.vacancy_since = None
            if self.state == WAITING:
                self._transition(ARMED, "returned to bed before the vacancy debounce", now)
            return
        self.vacancy_since = now
        if previous is not True or self.state != ARMED:
            return
        reason = self._wakeup_blocker(now)
        if reason:
            self.last_ignored = f"bed vacancy ignored: {reason}"
            self._log(self.last_ignored)
            return
        if self._transition(WAITING, "left bed in the morning window", now):
            self._schedule("vacancy", self.cfg.vacancy_debounce_s)

    def _wakeup_blocker(self, now: datetime) -> str | None:
        if self.window is None or not self.window.contains(now):
            return "outside the morning window"
        if self.session_start is None:
            return "no preceding bed occupancy"
        occupied_s = (now - self.session_start).total_seconds()
        if occupied_s < self.cfg.min_prior_occupancy_s:
            return f"only {occupied_s / 60:.0f} min of preceding bed occupancy"
        if not self.bed_health_ok:
            return "bed occupancy sensors unavailable"
        if self.home is not True:
            return "not home"
        if self.vacation:
            return "vacation or trip mode"
        if self.auto_brews_used >= self.cfg.max_auto_brews:
            return "automatic brew already used for this arming"
        return None

    def on_bed_health(self, ok: bool, now: datetime) -> None:
        now = _utc(now)
        self.bed_health_ok = ok
        if not ok and self.state == WAITING:
            self._transition(ARMED, "bed occupancy sensors unavailable", now)

    def on_presence(self, home: bool | None, now: datetime) -> None:
        now = _utc(now)
        self.home = home
        if home is False:
            self._away("you left home", now)

    def on_vacation(self, active: bool, now: datetime) -> None:
        now = _utc(now)
        self.vacation = active
        if active:
            self._away("vacation or trip mode turned on", now)

    def _away(self, reason: str, now: datetime) -> None:
        if self.state in ARMED_STATES:
            self._cancel_arming(reason, now)
        elif self.state in (STARTING, BREWING) and self.cfg.stop_brew_when_away:
            self._request_stop(f"safety ({reason})", now)

    def on_power_on_behavior(self, value: str | None, now: datetime) -> None:
        now = _utc(now)
        self.power_on_behavior = value
        self._enforce_power_on_behavior()
        self._recover_or_degrade(now)

    def on_telemetry(self, now: datetime) -> None:
        now = _utc(now)
        self.telemetry_at = now
        self._recover_or_degrade(now)

    def on_energy(self, kwh: float | None, now: datetime) -> None:
        self.energy_kwh = kwh

    def on_counter(self, brews_since_descale: int | None, last_descale: datetime | None) -> None:
        if brews_since_descale is not None:
            self.brews_since_descale = int(brews_since_descale)
        if last_descale is not None:
            self.last_descale = last_descale

    def on_plug(self, state: str | None, now: datetime) -> None:
        now = _utc(now)
        previous = self.plug
        if state == previous:
            return
        self.plug = state
        self.telemetry_at = now
        if state is None:
            # Only alarming when the plug may be energized; a plug that was
            # already confirmed off (e.g. while draining) is just unavailable.
            if previous == "on" or self.state in (STARTING, BREWING) or self.shutdown is not None:
                self._fault("plug_unavailable_during_brew",
                            "The coffee maker plug went unavailable while energized. Check the coffee "
                            "maker and unplug it if it is still heating.", now, level="critical")
            else:
                self._recover_or_degrade(now)
            return
        if state == "on":
            expected = self.expect_on_until is not None and now <= self.expect_on_until
            self.expect_on_until = None
            if expected and self.state == STARTING:
                return  # the ON this app just commanded
            # Anything else - including an ON while draining/ready after the
            # plug was confirmed off - is unexpected and handled below.
            if previous is None and self.started:
                # Came back from unavailable already energized: a power outage
                # with restore-to-previous, or a re-join. Never let that brew.
                self._fault("energized_after_power_restore",
                            "The coffee maker plug came back on after a power or network interruption "
                            "and was switched off. Check the plug's power-on behavior is OFF.", now)
                return
            self._manual_activation(now)
            return
        # state == "off"
        self._check_shutdown(now)
        if self.state in (STARTING, BREWING) and self.shutdown is None:
            self._emit("counter", "failed", "increment")
            self._finish_brew_record(now, success=False, reason="plug switched off externally")
            if self._transition(CANCELLED, "plug switched off externally", now):
                self._notify("stopped", "Coffee stopped", "The coffee maker plug was switched off during brewing.",
                             level="passive")
        self._recover_or_degrade(now)

    def _manual_activation(self, now: datetime) -> None:
        supervise = (
            self.cfg.manual_activation_policy == "supervise_if_home"
            and self.home is True
            and not self.vacation
            and self.state in (IDLE, ARMED, WAITING, READY, CANCELLED)
            and self.shutdown is None
        )
        if supervise:
            self._log("manual plug activation: supervising as a manual brew", "WARNING")
            self._start_brew("manual plug activation", now, automatic=False, plug_already_on=True)
            return
        self.request_shutdown("unexpected manual activation", now)
        self._notify("manual_shutoff", "Coffee maker switched off",
                     "The coffee maker plug was switched on outside the coffee station and was switched "
                     "off for safety.", tag=TAG_FAULT, level="time-sensitive")

    def on_power(self, watts: float | None, now: datetime) -> None:
        now = _utc(now)
        self.power = watts
        self.telemetry_at = now
        brew = self.brew
        if brew is not None:
            brew.sample(watts, now)
        if watts is None:
            if self.state in ACTIVE_STATES and self.plug != "off":
                self._fault("telemetry_lost", "The coffee maker power sensor went unavailable during "
                            "brewing, so the plug was switched off.", now)
            else:
                self._recover_or_degrade(now)
            return
        if self.state == STARTING and brew is not None:
            if watts >= self.cfg.heating_threshold_w:
                if brew.heat_above_since is None:
                    brew.heat_above_since = now
                    self._schedule("heat_confirm", self.cfg.heating_confirm_s)
            elif brew.heat_above_since is not None:
                brew.heat_above_since = None
                self._cancel("heat_confirm")
        elif self.state == BREWING and brew is not None:
            if watts < self.cfg.completion_threshold_w:
                if brew.below_since is None:
                    brew.below_since = now
                    self._schedule("completion", self.cfg.completion_debounce_s)
            elif brew.below_since is not None:
                # A momentary dip is not completion.
                brew.below_since = None
                brew.interruptions += 1
                self._cancel("completion")
        if self.plug == "off" and self.shutdown is None and watts > STUCK_RELAY_W:
            # Drawing real power while the switch says off: possible stuck
            # relay. Re-send OFF; the confirmation path escalates to a critical
            # "unplug" alert if the power does not drop.
            self._log(f"{watts:.0f} W while the plug reports off", "WARNING")
            self.request_shutdown("power drawn while the plug reports off", now)
        self._check_shutdown(now)
        self._recover_or_degrade(now)

    # ------------------------------------------------------------------ timers

    def on_timer(self, name: str, token: int, now: datetime) -> None:
        now = _utc(now)
        if self._timers.get(name) != token:
            return  # stale callback from a cancelled/replaced timer
        del self._timers[name]
        getattr(self, f"_timer_{name}")(now)

    def _timer_arming_expiry(self, now: datetime) -> None:
        if self.state in ARMED_STATES:
            self._cancel_arming("the arming window expired", now)

    def _timer_vacancy(self, now: datetime) -> None:
        if self.state != WAITING:
            return
        if self.bed is not False:
            self._transition(ARMED, "bed not confirmed vacant", now)
            return
        reason = self._wakeup_blocker_after_debounce(now)
        if reason:
            self._cancel_arming(f"automatic brew skipped: {reason}", now, level="time-sensitive")
            return
        problem = self._brew_blocker(now)
        if problem:
            self._cancel_arming(f"automatic brew skipped: {problem}", now, level="time-sensitive")
            return
        self._start_brew("wake-up", now, automatic=True)

    def _wakeup_blocker_after_debounce(self, now: datetime) -> str | None:
        if not self.bed_health_ok:
            return "bed occupancy sensors unavailable"
        if self.home is not True:
            return "not home"
        if self.vacation:
            return "vacation or trip mode"
        if self.auto_brews_used >= self.cfg.max_auto_brews:
            return "automatic brew already used for this arming"
        return None

    def _timer_startup(self, now: datetime) -> None:
        if self.state == STARTING and self.brew is not None and self.brew.heat_above_since is None:
            self._fault("failed_to_start",
                        f"The coffee maker did not start heating within {self.cfg.startup_timeout_s:.0f} s "
                        "(check the brewer's own switch and the plug). The plug was switched off.", now)

    def _timer_heat_confirm(self, now: datetime) -> None:
        brew = self.brew
        if (self.state == STARTING and brew is not None and brew.heat_above_since is not None
                and self.power is not None and self.power >= self.cfg.heating_threshold_w):
            brew.heating_started_at = brew.heat_above_since
            self._transition(BREWING, f"heating confirmed at {self.power:.0f} W", now)

    def _timer_completion(self, now: datetime) -> None:
        brew = self.brew
        if self.state != BREWING or brew is None or brew.below_since is None:
            return
        if self.power is not None and self.power >= self.cfg.completion_threshold_w:
            return
        brew.heating_ended_at = brew.below_since
        heating_s = (brew.below_since - (brew.heating_started_at or brew.started_at)).total_seconds()
        if heating_s < self.cfg.short_brew_s:
            self._fault("short_brew",
                        f"Heating stopped after only {heating_s:.0f} s; the reservoir may have been empty or "
                        "the brew interrupted. The plug was switched off.", now)
            return
        self._transition(DRAINING, f"heating complete after {heating_s:.0f} s", now)
        self._schedule("drainage", self.cfg.drainage_s)
        if self.cfg.keep_warm_s > 0:
            self._schedule("keep_warm", self.cfg.keep_warm_s)
            self._schedule("max_energized", self.cfg.keep_warm_s + 60)
        else:
            self.request_shutdown("heating complete", now)

    def _timer_drainage(self, now: datetime) -> None:
        if self.state != DRAINING or self.brew is None:
            return
        self.brew.drained = True
        if self.cfg.keep_warm_s > 0 or (self.shutdown is None and self.brew.off_confirmed):
            self._complete(now)
        # otherwise _check_shutdown completes the brew once the plug is confirmed off

    def _timer_keep_warm(self, now: datetime) -> None:
        self.request_shutdown("keep-warm period over", now)

    def _timer_max_energized(self, now: datetime) -> None:
        if self.plug != "off" or self.state in (STARTING, BREWING):
            self._fault("excessive_runtime",
                        f"The coffee maker was energized longer than {self.cfg.max_energized_s / 60:.0f} min "
                        "and was switched off.", now)

    def _timer_shutdown_confirm(self, now: datetime) -> None:
        if self.shutdown is None:
            return
        if self._plug_confirmed_off():
            self._check_shutdown(now)
            return
        if self.shutdown["attempts"] <= self.cfg.shutdown_retries:
            self.shutdown["attempts"] += 1
            self._log(f"shutdown not confirmed; retry {self.shutdown['attempts']}", "WARNING")
            self._emit("plug", "off")
            self._schedule("shutdown_confirm", self.cfg.shutdown_confirm_s)
            return
        # Keep re-sending OFF every minute while unconfirmed, but escalate the
        # critical alert with back-off (first, then every 15 min) instead of
        # paging every minute.
        last_alert = self.shutdown.get("alerted_at")
        if last_alert is None or (now - last_alert).total_seconds() >= 15 * 60:
            self.shutdown["alerted_at"] = now
            self._fault("shutdown_unconfirmed",
                        "The coffee maker plug could not be confirmed OFF. Unplug the coffee maker now.",
                        now, level="critical")
        else:
            self._emit("plug", "off")
        self._schedule("shutdown_confirm", max(self.cfg.shutdown_confirm_s, 60))

    def _timer_hold(self, now: datetime) -> None:
        if self.state in (READY, CANCELLED):
            if self.plug != "off":
                # e.g. a keep-warm plate: never leave the plug on past the hold.
                self.request_shutdown("display period over", now)
            self._transition(IDLE, f"{self.state} display period over", now)

    def tick(self, now: datetime) -> None:
        """Periodic supervision (telemetry freshness, maintenance by date)."""
        now = _utc(now)
        energized = self.state in (STARTING, BREWING) or (self.state == DRAINING and self.plug != "off")
        if energized:
            age = self.telemetry_age(now)
            if age is None or age > self.cfg.telemetry_stale_s:
                self._fault("stale_telemetry",
                            "No fresh power telemetry from the coffee maker plug during brewing, so it was "
                            "switched off.", now)
                return
        self._recover_or_degrade(now)
        if self.state in RESTING_STATES:
            self._check_maintenance(now)

    # ----------------------------------------------------------------- outputs

    def snapshot(self, now: datetime) -> dict[str, Any]:
        now = _utc(now)
        brew = self.brew
        elapsed = (now - brew.started_at).total_seconds() if brew else None
        heating_elapsed = (now - brew.heating_started_at).total_seconds() if brew and brew.heating_started_at else None
        if self.state == STARTING:
            progress = 0
        elif self.state == BREWING and heating_elapsed is not None:
            progress = min(95, int(100 * heating_elapsed / max(1.0, self.cfg.typical_heating_s)))
        elif self.state == DRAINING:
            progress = 97
        elif self.state == READY:
            progress = 100
        else:
            progress = None
        window = self.window or (self.next_window(now) if self.state not in (FAULT, UNAVAILABLE) else None)
        return {
            "state": self.state,
            "armed": self.state in ARMED_STATES,
            "brewing": self.state in (STARTING, BREWING),
            "ready": self.state == READY,
            "fault": self.state == FAULT,
            "available": not self.station_issues(now),
            "issues": self.station_issues(now),
            "fault_reason": self.fault_reason,
            "last_fault_reason": self.last_fault_reason,
            "last_transition": self.last_transition,
            "transition_reason": self.transition_reason,
            "last_ignored": self.last_ignored,
            "arming_source": self.arming_source,
            "armed_at": self.armed_at,
            "armed_until": self.armed_until,
            "window_start": window.start if window else None,
            "window_end": window.end if window else None,
            "brew_trigger_source": self.brew_trigger_source,
            "brew_elapsed_s": round(elapsed) if elapsed is not None else None,
            "brew_progress": progress,
            "last_power_w": self.power,
            "telemetry_age_s": round(self.telemetry_age(now)) if self.telemetry_at else None,
            "peak_power_w": round(brew.peak_power_w, 1) if brew else None,
            "last_successful_brew": self.last_successful_brew,
            "last_brew": self.last_brew,
            "auto_brews_used": self.auto_brews_used,
            "shutdown_pending": self.shutdown is not None,
            "plug": self.plug,
            "bed_occupied": self.bed,
            "home": self.home,
            "vacation": self.vacation,
            "remote_available": self.remote_available,
            "maintenance_due": self.maintenance_due(now),
            "brews_since_descale": self.brews_since_descale,
            "profile": self.cfg.profile,
        }


# ---------------------------------------------------------------------------
# AppDaemon adapter
# ---------------------------------------------------------------------------

ON_VALUES = {"on", "home", "true", "occupied"}
OFF_VALUES = {"off", "not_home", "away", "false", "unoccupied"}
INVALID_VALUES = {None, "unavailable", "unknown", "none", ""}


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ON_VALUES:
        return True
    if text in OFF_VALUES:
        return False
    return None


def parse_float(value: Any) -> float | None:
    if value is None or str(value).strip().lower() in INVALID_VALUES:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_dt(value: Any) -> datetime | None:
    if not value or str(value).lower() in INVALID_VALUES:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso(v) for v in value]
    return value


REQUIRED_ARGS = ("switch_entity", "power_entity", "bed_entity", "presence_entity", "notify_service")


class CoffeeStation(_HassBase):  # type: ignore[misc, valid-type]
    """AppDaemon adapter around CoffeeCore."""

    # ----------------------------------------------------------- lifecycle

    def initialize(self) -> None:
        self._lock = threading.RLock()
        self._handles: dict[str, Any] = {}
        self._last_published: dict[str, Any] = {}
        args = dict(self.args or {})
        missing = [key for key in REQUIRED_ARGS if not args.get(key)]
        if missing:
            self.log(f"coffee_station disabled: missing required args {missing}", level="ERROR")
            self.core = None
            return
        try:
            cfg = CoffeeConfig.from_args(args)
        except ValueError as err:
            self.log(f"coffee_station disabled: invalid configuration: {err}", level="ERROR")
            self.core = None
            return
        pob = args.get("power_on_behavior_entity")
        if pob and self._entity(pob) is None:
            # Don't lock the station out forever over a misnamed/absent entity.
            self.log(f"coffee_station: power_on_behavior_entity {pob} does not exist; power-on behavior "
                     "cannot be enforced - set it to OFF on the plug manually", level="ERROR")
            args.pop("power_on_behavior_entity")
            cfg.has_power_on_behavior = False
        self.cfg_args = args
        self.core = CoffeeCore(cfg)
        self._listen()
        self._resync("initialize")
        self.run_every(self._on_tick, "now+5", cfg.tick_s)

    def terminate(self) -> None:
        # Arming is never carried across a reload. Leave the plug as-is here:
        # the next initialize() switches it off if it is still energized.
        self.log("coffee_station terminating; arming will be cleared on restart")

    def _now(self) -> datetime:
        now = self.get_now()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def _listen(self) -> None:
        a = self.cfg_args
        self.listen_state(self._cb_plug, a["switch_entity"])
        self.listen_state(self._cb_power, a["power_entity"])
        if a.get("energy_entity"):
            self.listen_state(self._cb_energy, a["energy_entity"])
        for entity in a.get("liveness_entities") or []:
            self.listen_state(self._cb_liveness, entity)
        if a.get("power_on_behavior_entity"):
            self.listen_state(self._cb_power_on_behavior, a["power_on_behavior_entity"])
        if a.get("remote_action_entity"):
            self.listen_state(self._cb_remote, a["remote_action_entity"])
        self.listen_state(self._cb_bed, a["bed_entity"])
        for entity in a.get("bed_health_entities") or []:
            self.listen_state(self._cb_bed_health, entity)
        self.listen_state(self._cb_presence, a["presence_entity"])
        for entity in a.get("vacation_entities") or []:
            self.listen_state(self._cb_vacation, entity)
        for kind, key in (("arm", "arm_button"), ("brew_now", "brew_now_button"), ("stop", "stop_button"),
                          ("acknowledge", "acknowledge_button"), ("reset_maintenance", "reset_maintenance_button")):
            if a.get(key):
                self.listen_state(self._cb_button, a[key], kind=kind)
        if a.get("brews_since_descale_counter"):
            self.listen_state(self._cb_counter, a["brews_since_descale_counter"])
        self.listen_event(self._cb_notification_action, "mobile_app_notification_action")
        # HA restarted underneath us: treat exactly like an app restart.
        self.listen_event(self._cb_plugin_started, "plugin_started")

    # ------------------------------------------------------------ snapshot

    def _entity(self, entity_id: str | None) -> dict[str, Any] | None:
        if not entity_id:
            return None
        try:
            return self.get_state(entity_id, attribute="all")
        except Exception as err:  # pragma: no cover - defensive
            self.log(f"could not read {entity_id}: {err}", level="WARNING")
            return None

    def _state_of(self, entity_id: str | None) -> Any:
        data = self._entity(entity_id)
        return data.get("state") if isinstance(data, dict) else None

    def _updated_at(self, entity_id: str) -> datetime | None:
        data = self._entity(entity_id)
        if not isinstance(data, dict):
            return None
        stamps = [parse_dt(data.get(k)) for k in ("last_reported", "last_updated", "last_changed")]
        stamps = [s for s in stamps if s]
        return max(stamps) if stamps else None

    def _vacation_active(self) -> bool:
        return any(parse_bool(self._state_of(e)) is True for e in self.cfg_args.get("vacation_entities") or [])

    def _bed_health_ok(self) -> bool:
        return all(str(self._state_of(e)).lower() not in INVALID_VALUES
                   for e in self.cfg_args.get("bed_health_entities") or [])

    def _snapshot(self) -> dict[str, Any]:
        a = self.cfg_args
        plug_state = self._state_of(a["switch_entity"])
        plug = plug_state if plug_state in ("on", "off") else None
        bed_data = self._entity(a["bed_entity"]) or {}
        telemetry = [self._updated_at(e) for e in [a["power_entity"], *(a.get("liveness_entities") or [])]]
        telemetry = [t for t in telemetry if t]
        counter = parse_float(self._state_of(a.get("brews_since_descale_counter")))
        return {
            "plug": plug,
            "power": parse_float(self._state_of(a["power_entity"])),
            "energy_kwh": parse_float(self._state_of(a.get("energy_entity"))),
            "telemetry_at": max(telemetry) if telemetry else None,
            "bed": parse_bool(bed_data.get("state")),
            "bed_since": parse_dt(bed_data.get("last_changed")),
            "bed_health_ok": self._bed_health_ok(),
            "home": parse_bool(self._state_of(a["presence_entity"])),
            "vacation": self._vacation_active(),
            "power_on_behavior": self._state_of(a.get("power_on_behavior_entity")),
            "remote_available": str(self._state_of(a.get("remote_action_entity"))).lower() != "unavailable",
            "brews_since_descale": int(counter) if counter is not None else 0,
            "last_descale": parse_dt(self._state_of(a.get("last_descale_entity"))),
        }

    def _load_previous(self) -> dict[str, Any]:
        try:
            with open(STATE_FILE, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return {}

    def _resync(self, why: str) -> None:
        with self._lock:
            for handle, _token in list(self._handles.values()):
                self._safe_cancel(handle)
            self._handles.clear()
            # HA may have lost every set_state entity: publish all of them again.
            self._last_published.clear()
            self.log(f"coffee_station resync ({why})")
            self.core.on_start(self._now(), self._snapshot(), self._load_previous())
            self._run_effects()

    # ------------------------------------------------------------ callbacks

    def _guard(self, fn, *args) -> None:
        if self.core is None:
            return
        with self._lock:
            try:
                fn(*args)
            except Exception as err:  # never let a bad event kill the app silently
                self.log(f"coffee_station callback error: {err!r}", level="ERROR")
                self.core.request_shutdown("internal error", self._now())
            self._run_effects()

    def _cb_plug(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_plug, new if new in ("on", "off") else None, self._now())

    def _cb_power(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_power, parse_float(new), self._now())

    def _cb_energy(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_energy, parse_float(new), self._now())

    def _cb_liveness(self, entity, attribute, old, new, kwargs) -> None:
        if str(new).lower() in INVALID_VALUES:
            return
        self._guard(self.core.on_telemetry, self._now())

    def _cb_power_on_behavior(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_power_on_behavior, None if str(new).lower() in INVALID_VALUES else new, self._now())

    def _cb_remote(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self._remote_update, new)

    def _remote_update(self, new: Any) -> None:
        self.core.remote_available = str(new).lower() != "unavailable"
        if str(new).lower() not in INVALID_VALUES:
            self.core.on_remote(str(new), self._now())

    def _cb_bed(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_bed, parse_bool(new), self._now())

    def _cb_bed_health(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_bed_health, self._bed_health_ok(), self._now())

    def _cb_presence(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_presence, parse_bool(new), self._now())

    def _cb_vacation(self, entity, attribute, old, new, kwargs) -> None:
        self._guard(self.core.on_vacation, self._vacation_active(), self._now())

    def _cb_button(self, entity, attribute, old, new, kwargs) -> None:
        if str(new).lower() in INVALID_VALUES or old is None or str(old).lower() == "unavailable":
            return  # helper (re)loading, not a press
        self._guard(self.core.request, kwargs["kind"], "dashboard", self._now())

    def _cb_counter(self, entity, attribute, old, new, kwargs) -> None:
        value = parse_float(new)
        if value is not None:
            self._guard(self.core.on_counter, int(value), None)

    def _cb_notification_action(self, event_name, data, kwargs) -> None:
        action = (data or {}).get("action")
        kind = {"COFFEE_STOP": "stop", "COFFEE_DISARM": "disarm"}.get(action)
        if kind:
            self._guard(self.core.request, kind, "notification", self._now())

    def _cb_plugin_started(self, event_name, data, kwargs) -> None:
        if self.core is not None:
            self._resync("Home Assistant reconnected")

    def _on_tick(self, kwargs) -> None:
        self._guard(self.core.tick, self._now())

    def _on_timer(self, kwargs) -> None:
        self._guard(self._fire_timer, kwargs["timer_name"], kwargs["token"])

    def _fire_timer(self, name: str, token: int) -> None:
        # Only forget the handle if it is the one that fired; a stale callback
        # must not drop the handle of its replacement.
        current = self._handles.get(name)
        if current is not None and current[1] == token:
            del self._handles[name]
        self.core.on_timer(name, token, self._now())

    # -------------------------------------------------------------- effects

    def _safe_cancel(self, handle: Any) -> None:
        try:
            self.cancel_timer(handle)
        except Exception:  # pragma: no cover - already fired
            pass

    def _run_effects(self) -> None:
        for effect in self.core.drain():
            try:
                self._run_effect(effect)
            except Exception as err:
                self.log(f"coffee_station effect {effect[0]} failed: {err!r}", level="ERROR")
        self._publish()

    def _run_effect(self, effect: tuple) -> None:
        kind = effect[0]
        a = self.cfg_args
        if kind == "plug":
            self.call_service(f"switch/turn_{effect[1]}", entity_id=a["switch_entity"])
        elif kind == "timer":
            _, name, delay, token = effect
            if name in self._handles:
                self._safe_cancel(self._handles.pop(name)[0])
            self._handles[name] = (self.run_in(self._on_timer, delay, timer_name=name, token=token), token)
        elif kind == "cancel_timer":
            entry = self._handles.pop(effect[1], None)
            if entry is not None:
                self._safe_cancel(entry[0])
        elif kind == "notify":
            self._notify(effect[1])
        elif kind == "clear_notification":
            self.call_service(a["notify_service"], message="clear_notification", data={"tag": effect[1]})
        elif kind == "counter":
            entity = a.get({"total": "total_brews_counter", "since_descale": "brews_since_descale_counter",
                            "failed": "failed_brews_counter"}[effect[1]])
            if entity:
                self.call_service(f"counter/{effect[2]}", entity_id=entity)
        elif kind == "record_brew":
            self._record_brew(effect[1])
        elif kind == "set_last_descale" and a.get("last_descale_entity"):
            self.call_service("input_datetime/set_datetime", entity_id=a["last_descale_entity"],
                              timestamp=effect[1].timestamp())
        elif kind == "set_power_on_behavior" and a.get("power_on_behavior_entity"):
            self.call_service("select/select_option", entity_id=a["power_on_behavior_entity"], option=effect[1])
        elif kind == "feedback" and a.get("feedback_light"):
            self.call_service("light/turn_on", entity_id=a["feedback_light"], flash="short")
        elif kind == "persist":
            self._persist(effect[1])
        elif kind == "log":
            self.log(effect[2], level=effect[1])

    def _notify(self, payload: dict[str, Any]) -> None:
        a = self.cfg_args
        url = a.get("dashboard_url", "/db-coffee/coffee")
        actions = []
        for action in payload["actions"]:
            actions.append({"action": action, "title": {"COFFEE_STOP": "Stop coffee",
                                                         "COFFEE_DISARM": "Disarm"}.get(action, action)})
        actions.append({"action": "URI", "title": "Coffee", "uri": url})
        push: dict[str, Any] = {"interruption-level": payload["level"]}
        data: dict[str, Any] = {"tag": payload["tag"], "group": "coffee_station", "url": url, "clickAction": url,
                                "actions": actions}
        if payload["level"] == "critical":
            push = {"interruption-level": "critical", "sound": {"name": "default", "critical": 1, "volume": 1.0}}
            # Android ignores `push`; these make it ring through Do Not Disturb.
            data.update({"ttl": 0, "priority": "high", "channel": "alarm_stream"})
        data["push"] = push
        try:
            self.call_service(a["notify_service"], title=payload["title"], message=payload["message"], data=data)
        finally:
            if payload["tag"] == TAG_FAULT:
                # A second, local channel for faults: survives a failed push.
                self.call_service("persistent_notification/create", title=payload["title"],
                                  message=payload["message"], notification_id="coffee_station_fault")

    def _record_brew(self, brew: dict[str, Any]) -> None:
        a = self.cfg_args
        for key, arg in (("heating_s", "last_brew_duration_entity"), ("energy_wh", "last_brew_energy_entity"),
                         ("peak_power_w", "last_brew_peak_power_entity")):
            if a.get(arg):
                self.call_service("input_number/set_value", entity_id=a[arg], value=brew[key])
        if a.get("last_brew_entity"):
            self.call_service("input_datetime/set_datetime", entity_id=a["last_brew_entity"],
                              timestamp=brew["finished_at"].timestamp())

    def _persist(self, payload: dict[str, Any]) -> None:
        try:
            tmp = f"{STATE_FILE}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, STATE_FILE)
        except OSError as err:
            self.log(f"could not persist coffee_station state: {err}", level="WARNING")

    # -------------------------------------------------------------- publish

    def _publish(self) -> None:
        snap = self.core.snapshot(self._now())
        attrs = _iso({k: v for k, v in snap.items() if k not in ("state",)})
        def binary(entity_id: str, on: bool, attributes: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            icon_on, icon_off = BINARY_ICONS[entity_id]
            return ("on" if on else "off", {**attributes, "icon": icon_on if on else icon_off})

        fault_reason = snap["fault_reason"]
        progress = snap["brew_progress"]
        entities = {
            "sensor.coffee_state": (snap["state"], {**attrs, "friendly_name": "Coffee station",
                                                    "icon": STATE_ICONS[snap["state"]]}),
            "binary_sensor.coffee_armed": binary("binary_sensor.coffee_armed", snap["armed"],
                                                 {"friendly_name": "Coffee armed"}),
            "binary_sensor.coffee_brewing": binary("binary_sensor.coffee_brewing", snap["brewing"],
                                                   {"friendly_name": "Coffee brewing", "device_class": "running"}),
            "binary_sensor.coffee_ready": binary("binary_sensor.coffee_ready", snap["ready"],
                                                 {"friendly_name": "Coffee ready"}),
            "binary_sensor.coffee_station_available": binary(
                "binary_sensor.coffee_station_available", snap["available"],
                {"friendly_name": "Coffee station available", "device_class": "connectivity",
                 "issues": snap["issues"]}),
            "binary_sensor.coffee_maintenance_due": binary(
                "binary_sensor.coffee_maintenance_due", snap["maintenance_due"],
                {"friendly_name": "Coffee maker descale due", "device_class": "problem",
                 "brews_since_descale": snap["brews_since_descale"]}),
            "sensor.coffee_fault": (fault_reason or "none",
                                    {"friendly_name": "Coffee fault",
                                     "icon": "mdi:alert-octagon" if fault_reason else "mdi:check-circle-outline",
                                     "last_fault_reason": snap["last_fault_reason"]}),
            "sensor.coffee_armed_until": (_iso(snap["armed_until"]) or "unknown",
                                          {"friendly_name": "Coffee armed until", "device_class": "timestamp",
                                           "icon": "mdi:timer-sand" if snap["armed"] else "mdi:timer-off-outline"}),
            "sensor.coffee_armed_at": (_iso(snap["armed_at"]) or "unknown",
                                       {"friendly_name": "Coffee armed at", "device_class": "timestamp",
                                        "icon": "mdi:coffee-maker-check" if snap["armed"]
                                        else "mdi:coffee-maker-outline"}),
            "sensor.coffee_next_window": (_iso(snap["window_start"]) or "unknown",
                                          {"friendly_name": "Coffee next wake-up window",
                                           "device_class": "timestamp", "icon": "mdi:weather-sunset-up",
                                           "window_end": _iso(snap["window_end"])}),
            "sensor.coffee_brew_progress": (progress if progress is not None else "unknown",
                                            {"friendly_name": "Coffee brew progress",
                                             "unit_of_measurement": "%",
                                             "icon": "mdi:progress-check" if progress == 100
                                             else "mdi:progress-clock",
                                             "brew_elapsed_s": snap["brew_elapsed_s"]}),
        }
        volatile = {"telemetry_age_s", "brew_elapsed_s", "last_power_w"}
        active = snap["state"] in ACTIVE_STATES
        for entity_id, (state, attributes) in entities.items():
            key_attrs = attributes if active else {k: v for k, v in attributes.items() if k not in volatile}
            signature = (state, json.dumps(key_attrs, sort_keys=True, default=str))
            if self._last_published.get(entity_id) == signature:
                continue
            self._last_published[entity_id] = signature
            self.set_state(entity_id, state=state, attributes=attributes)
