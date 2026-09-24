"""Watch the rtlamr2mqtt add-on (RTL-SDR gas meter bridge) and, if it stays
stuck, escalate to a power-cycle of the Proxmox host the RTL-SDR USB dongle
is passed through to.

Why this exists: a USB/kernel-level fault on the dongle can't be cleared by
restarting the add-on container - only a power-cycle of the host it's passed
through to clears it. Supervisor's own `watchdog: true` on the add-on only
restarts the add-on container itself; it never sees the add-on's *internal*
retry loop around the `rtlamr` binary (see below), so a stuck dongle can hide
behind a container that looks perfectly "started".

Failure detection requires BOTH signals to agree, never either alone:
  1. The gas-meter sensors have gone stale (no new reading for a while).
  2. The add-on's own logs show a known failure pattern.
Anything the app can't verify for sure - the sensor is missing, the logs
can't be fetched, no known pattern matches - is treated as "can't tell" and
is a no-op, never an escalation. See appdaemon/apps/reboot.py's history
comments for why: a broken probe that always reports failure reboot-loops
the thing it's supposed to protect (incidents 2026-09-01 and 2026-09-08).

The add-on already retries the `rtlamr` process internally on its own
("rtlamr process died (exit code: N), attempting restart" - a real example
seen live on 2026-09-24). A couple of these are normal jitter; a burst of
them in one log fetch, with readings actually stale, means the internal
retries aren't fixing it - see DEATH_LOOP_PATTERN / death_loop_min_count.

Escalation ladder (mirrors packages/z2m_lifecycle.yaml's
shutdown_proxmox_z2m_unavailable automation and reboot.py's cooldown/notify
pattern): notify -> restart the add-on (up to max_restart_attempts) -> after
a cooldown, shut down the Proxmox host via rest_command.proxmox_shutdown
(defined in packages/zigbee_zwave.yaml). Unlike reboot.py, a shutdown sets a
"pending verification" flag that blocks any further automatic shutdown until
a fresh reading is actually seen - a power-cycle that didn't fix it can never
trigger a second automatic shutdown on its own.

Ships with dry_run: true. In dry-run the app still walks the whole decision
and escalation ladder and notifies at every stage, but never calls
hassio/addon_restart or rest_command/proxmox_shutdown. Flip dry_run: false in
apps.yaml only after watching it run for real - see docs/rtlsdr_watchdog.md.

apps.yaml args (all optional; see apps.yaml for the live values):
  dry_run: log/notify what the app WOULD do instead of acting (default True)
  addon_slug: the rtlamr2mqtt add-on's Supervisor slug
  reading_entity / last_seen_entity: the gas-meter sensors to watch
  logs_url: full URL to fetch add-on logs from (default: Core's hassio proxy)
  ha_token: fallback bearer token for logs_url if SUPERVISOR_TOKEN is refused
  check_interval_minutes: minutes between evaluation cycles (default 5)
  stale_after_minutes: minutes with no new reading before "stale" (default 60)
  confirm_cycles: consecutive unhealthy cycles required before escalating (default 2)
  log_tail_lines: how many trailing log lines to keep for matching (default 300)
  log_fetch_timeout_seconds: HTTP timeout for the log fetch (default 10)
  death_loop_min_count: "rtlamr process died" occurrences in one fetched tail
                         that count as a USB-fault-tier hit (default 5)
  startup_grace_minutes: skip evaluation for this long after init (default 20)
  max_restart_attempts: add-on restarts to try before considering a shutdown (default 3)
  restart_settle_minutes: minutes to wait after a restart before re-evaluating (default 25)
  pre_action_delay_seconds: delay between a notify and the restart it describes (default 30)
  shutdown_notice_seconds: delay between the shutdown notify and the shutdown itself (default 60)
  min_shutdown_interval_hours: minimum spacing between automatic shutdowns (default 24)
  renotify_minutes: minimum spacing between repeats of the same "can't tell" notice (default 120)
  notify_service: primary notify service (default notify/mobile_app_wethop)
  secondary_notify_service: also notified at the Proxmox-shutdown stage (optional)
  usb_fault_patterns / generic_error_patterns: override the built-in pattern lists
"""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import hassapi as hass

ADDON_SLUG_DEFAULT = "6713e36e_rtlamr2mqtt"
# The add-on's own wrapper-script timestamps (`[2026-09-24 09:38:00,059] ...`)
# carry no offset; they're the container's local time, which matches HA's
# configured time_zone (appdaemon/appdaemon.yaml). Used only to time-correlate
# log evidence with the current stale period - see _match_logs().
ADDON_LOG_LOCAL_TZ = ZoneInfo("America/Chicago")
STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".rtlsdr_watchdog_state.json"
)

# Hardware-level faults. A single occurrence of any of these is USB-fault-tier
# evidence on its own - these are the strings that justify shutting down the
# host, once the restart ladder is exhausted.
USB_FAULT_PATTERNS = (
    "usb_claim_interface error",
    "usb_open error",
    "no supported devices found",
    "failed to open rtlsdr device",
    "rtl_tcp: error",
    "libusb_error",
    "rtlsdr_read_async returned",
    "cb transfer status",
)

# The add-on respawns its own `rtlamr` subprocess on death; a couple of these
# is normal jitter, not a hardware fault. Only a burst (>= death_loop_min_count
# occurrences in one fetched tail) is promoted to USB-fault-tier evidence.
DEATH_LOOP_PATTERN = "rtlamr process died"

# Can justify restarting the add-on, but never a Proxmox shutdown on their
# own - e.g. "Errno 111" (connection refused) also fires when EMQX restarts,
# which is not a USB fault.
GENERIC_ERROR_PATTERNS = (
    "traceback (most recent call last)",
    "errno",
    "connection refused",
)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Two timestamp formats appear in the add-on's log, both anchored at line
# start (after ANSI stripping): the wrapper script's own naive local-time
# bracket ("[2026-09-24 09:38:00,059] ...") and the rtlamr binary's own
# tz-aware logfmt line ("time=2026-09-24T09:38:00.058-05:00 level=...").
LINE_TS_BRACKET_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\]")
LINE_TS_LOGFMT_RE = re.compile(r"^\s*time=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2})")

_DEFAULT_STATE = {
    "restart_attempts": 0,
    "last_restart_ts": None,
    "last_shutdown_ts": None,
    "shutdown_pending_verification": False,
}


class RtlSdrWatchdog(hass.Hass):

    def initialize(self):
        self.dry_run = bool(self.args.get("dry_run", True))
        self.addon_slug = self.args.get("addon_slug", ADDON_SLUG_DEFAULT)
        self.reading_entity = self.args.get(
            "reading_entity", "sensor.raw_house_gas_meter_reading"
        )
        self.last_seen_entity = self.args.get(
            "last_seen_entity", "sensor.raw_house_gas_meter_last_seen"
        )
        self.ha_token = self.args.get("ha_token")
        # The Supervisor-proxy route only accepts SUPERVISOR_TOKEN. If the
        # operator has switched to the ha_token fallback (per
        # docs/rtlsdr_watchdog.md), default to the matching HA Core REST
        # endpoint too - unless logs_url was set explicitly, which always
        # wins regardless of which token is in play.
        default_logs_url = (
            "http://homeassistant:8123/api/hassio/addons/{}/logs".format(self.addon_slug)
            if self.ha_token
            else "http://supervisor/core/api/hassio/addons/{}/logs".format(self.addon_slug)
        )
        self.logs_url = self.args.get("logs_url", default_logs_url)

        self.check_interval = int(self.args.get("check_interval_minutes", 5)) * 60
        self.stale_after = timedelta(minutes=float(self.args.get("stale_after_minutes", 60)))
        self.confirm_cycles = int(self.args.get("confirm_cycles", 2))
        self.log_tail_lines = int(self.args.get("log_tail_lines", 300))
        self.log_fetch_timeout = float(self.args.get("log_fetch_timeout_seconds", 10))
        self.death_loop_min_count = int(self.args.get("death_loop_min_count", 5))
        self.startup_grace = timedelta(minutes=float(self.args.get("startup_grace_minutes", 20)))
        self.max_restart_attempts = int(self.args.get("max_restart_attempts", 3))
        self.restart_settle = timedelta(minutes=float(self.args.get("restart_settle_minutes", 25)))
        self.pre_action_delay = int(self.args.get("pre_action_delay_seconds", 30))
        self.shutdown_notice_seconds = int(self.args.get("shutdown_notice_seconds", 60))
        self.min_shutdown_interval = timedelta(
            hours=float(self.args.get("min_shutdown_interval_hours", 24))
        )
        self.renotify_after = timedelta(minutes=float(self.args.get("renotify_minutes", 120)))
        self.notify_service = self.args.get("notify_service", "notify/mobile_app_wethop")
        self.secondary_notify_service = self.args.get("secondary_notify_service")
        self.usb_fault_patterns = tuple(
            p.lower() for p in self.args.get("usb_fault_patterns", USB_FAULT_PATTERNS)
        )
        self.generic_error_patterns = tuple(
            p.lower() for p in self.args.get("generic_error_patterns", GENERIC_ERROR_PATTERNS)
        )

        self.started_at = self._now()
        self.unhealthy_cycles = 0
        self._last_notice_at = {}
        self.state = self._load_state()

        self.log(
            "rtlsdr_watchdog init: dry_run={} addon={} stale_after={} confirm_cycles={} "
            "death_loop_min_count={} max_restart_attempts={} restart_settle={} "
            "min_shutdown_interval={}".format(
                self.dry_run,
                self.addon_slug,
                self.stale_after,
                self.confirm_cycles,
                self.death_loop_min_count,
                self.max_restart_attempts,
                self.restart_settle,
                self.min_shutdown_interval,
            )
        )

        self.run_every(self.check, self._now() + timedelta(seconds=30), self.check_interval)
        self.listen_event(self._manual_reset, "rtlsdr_watchdog_reset")

    # -- small helpers, each independently testable -------------------------

    def _now(self):
        return self.datetime(aware=True)

    def _fetch_logs(self):
        token = self.ha_token or os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            self.log("rtlsdr_watchdog: no SUPERVISOR_TOKEN/ha_token available", level="WARNING")
            return None
        request = urllib.request.Request(
            self.logs_url,
            headers={"Authorization": "Bearer {}".format(token), "Accept": "text/plain"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.log_fetch_timeout) as response:
                if response.status != 200:
                    self.log(
                        "rtlsdr_watchdog: log fetch returned HTTP {}".format(response.status),
                        level="WARNING",
                    )
                    return None
                text = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as err:
            self.log("rtlsdr_watchdog: log fetch failed: {}".format(err), level="WARNING")
            return None

        text = ANSI_RE.sub("", text)
        lines = text.splitlines()[-self.log_tail_lines:]
        return "\n".join(lines)

    def _line_timestamp(self, line):
        """Parse a log line's own timestamp, tz-aware. None if it has none."""
        match = LINE_TS_LOGFMT_RE.match(line)
        if match:
            return self._parse_ts(match.group(1))
        match = LINE_TS_BRACKET_RE.match(line)
        if match:
            try:
                naive = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
            return naive.replace(tzinfo=ADDON_LOG_LOCAL_TZ)
        return None

    def _relevant_log_text(self, text, since):
        """Drop log lines that predate `since` (the last known-good reading).

        Without this, a USB error that scrolled into view during a past,
        already-recovered outage can sit in the fetched tail indefinitely and
        keep matching on every later, unrelated stale period - see the
        docstring's "temporally correlated" requirement. A line with no
        timestamp of its own (e.g. an indented traceback continuation)
        inherits the most recently seen timestamp, so multi-line evidence
        blocks stay attached to the event that produced them.
        """
        if since is None:
            return text
        kept = []
        current_ts = None
        for line in text.splitlines():
            ts = self._line_timestamp(line)
            if ts is not None:
                current_ts = ts
            if current_ts is not None and current_ts >= since:
                kept.append(line)
        return "\n".join(kept)

    def _match_logs(self, text, since=None):
        if not text:
            return [], []
        text = self._relevant_log_text(text, since)
        if not text:
            return [], []
        lowered = text.lower()
        usb_hits = [p for p in self.usb_fault_patterns if p in lowered]
        generic_hits = [p for p in self.generic_error_patterns if p in lowered]

        death_count = lowered.count(DEATH_LOOP_PATTERN)
        if death_count >= self.death_loop_min_count:
            usb_hits.append("{} ({}x)".format(DEATH_LOOP_PATTERN, death_count))

        return usb_hits, generic_hits

    def _parse_ts(self, value):
        if not value or not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _last_reading_at(self):
        candidates = []
        for entity, attribute in (
            (self.reading_entity, "last_updated"),
            (self.last_seen_entity, "last_updated"),
        ):
            try:
                value = self.get_state(entity, attribute=attribute)
            except Exception:  # noqa: BLE001 - entity may not exist yet
                value = None
            ts = self._parse_ts(value)
            if ts is not None:
                candidates.append(ts)

        try:
            state_value = self.get_state(self.last_seen_entity)
        except Exception:  # noqa: BLE001
            state_value = None
        ts = self._parse_ts(state_value)
        if ts is not None:
            candidates.append(ts)

        if not candidates:
            return None
        return max(c if c.tzinfo else c.replace(tzinfo=timezone.utc) for c in candidates)

    def _is_stale(self, now, last):
        if last is None:
            return None
        last_restart_ts = self._parse_ts(self.state.get("last_restart_ts"))
        if last_restart_ts is not None and last <= last_restart_ts:
            return True
        return (now - last) >= self.stale_after

    def _load_state(self):
        try:
            with open(STATE_FILE) as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return dict(_DEFAULT_STATE)
        state = dict(_DEFAULT_STATE)
        state.update({k: data.get(k, v) for k, v in _DEFAULT_STATE.items()})
        return state

    def _save_state(self):
        """Persist self.state to disk. Returns True on success.

        In dry-run, state changes stay in memory only (so the ladder still
        progresses realistically within one dry-run session) but are never
        written - otherwise simulated restart/shutdown counters would still
        be sitting on disk the moment dry_run is flipped to False, making the
        watchdog think restarts are already exhausted or a shutdown is
        already pending verification before it has ever taken a real action.
        """
        if self.dry_run:
            self.log(
                "rtlsdr_watchdog: [DRY RUN] not persisting state: {}".format(self.state),
                level="DEBUG",
            )
            return True
        try:
            with open(STATE_FILE, "w") as handle:
                json.dump(self.state, handle)
            return True
        except OSError as err:
            self.log("rtlsdr_watchdog: could not write {}: {}".format(STATE_FILE, err), level="WARNING")
            return False

    def _notify(self, title, message, key=None):
        if key is not None:
            now = self._now()
            last = self._last_notice_at.get(key)
            if last is not None and (now - last) < self.renotify_after:
                return
            self._last_notice_at[key] = now

        if self.dry_run:
            title = "[DRY RUN] " + title

        for service in filter(None, (self.notify_service, self.secondary_notify_service if key == "shutdown" else None)):
            try:
                self.call_service(service, title=title, message=message)
            except Exception as err:  # noqa: BLE001
                self.log("rtlsdr_watchdog: notify via {} failed: {}".format(service, err), level="WARNING")

    def _manual_reset(self, event_name, data, kwargs):
        self.state = dict(_DEFAULT_STATE)
        self._save_state()
        self.unhealthy_cycles = 0
        self.log("rtlsdr_watchdog: state manually reset via rtlsdr_watchdog_reset event")

    # -- decision logic -------------------------------------------------------

    def check(self, kwargs):
        now = self._now()

        if now < self.started_at + self.startup_grace:
            self.log("rtlsdr_watchdog: in startup grace window, skipping", level="DEBUG")
            return

        last_restart_ts = self._parse_ts(self.state.get("last_restart_ts"))
        if last_restart_ts is not None and now < last_restart_ts + self.restart_settle:
            self.log("rtlsdr_watchdog: in post-restart settle window, skipping", level="DEBUG")
            return

        last_reading_at = self._last_reading_at()
        stale = self._is_stale(now, last_reading_at)

        if stale is None:
            self._notify(
                "RTL-SDR watchdog: can't read gas meter sensor",
                "{} / {} did not return a usable timestamp. Taking no action.".format(
                    self.reading_entity, self.last_seen_entity
                ),
                key="no_sensor",
            )
            self.unhealthy_cycles = 0
            return

        if not stale:
            if self.state.get("restart_attempts") or self.state.get("shutdown_pending_verification"):
                self._notify(
                    "RTL-SDR watchdog: recovered",
                    "Gas meter readings are fresh again. Clearing restart/shutdown state.",
                )
                self.state["restart_attempts"] = 0
                self.state["shutdown_pending_verification"] = False
                self._save_state()
            self.unhealthy_cycles = 0
            return

        logs = self._fetch_logs()
        if logs is None:
            self._notify(
                "RTL-SDR watchdog: gas meter stale, can't read add-on logs",
                "Readings are stale but the rtlamr2mqtt add-on log couldn't be fetched. "
                "Taking no action.",
                key="no_logs",
            )
            self.unhealthy_cycles = 0
            return

        usb_hits, generic_hits = self._match_logs(logs, since=last_reading_at)
        if not usb_hits and not generic_hits:
            self._notify(
                "RTL-SDR watchdog: gas meter stale, no known error in logs",
                "Readings are stale but no known failure pattern matched the add-on log. "
                "Taking no action.",
                key="stale_no_match",
            )
            self.unhealthy_cycles = 0
            return

        self.unhealthy_cycles += 1
        self.log(
            "rtlsdr_watchdog: unhealthy cycle {}/{} (usb_hits={} generic_hits={})".format(
                self.unhealthy_cycles, self.confirm_cycles, usb_hits, generic_hits
            ),
            level="WARNING",
        )
        if self.unhealthy_cycles < self.confirm_cycles:
            return

        self.unhealthy_cycles = 0
        self._escalate(usb_fault=bool(usb_hits), evidence=(usb_hits or generic_hits)[:3])

    # -- escalation -------------------------------------------------------

    def _escalate(self, usb_fault, evidence):
        if self.state.get("restart_attempts", 0) < self.max_restart_attempts:
            self._restart_stage(evidence)
            return
        self._shutdown_stage(usb_fault, evidence)

    def _restart_stage(self, evidence):
        # Deliberately does NOT touch state.restart_attempts yet - only
        # _do_restart, once hassio/addon_restart has actually been
        # dispatched, counts the attempt. If AppDaemon reloads during
        # pre_action_delay (losing the scheduled run_in callback) or the
        # service call raises, nothing was ever consumed, so the next
        # unhealthy cycle simply retries instead of silently burning one of
        # max_restart_attempts on a restart that never happened.
        attempt = self.state.get("restart_attempts", 0) + 1
        self._notify(
            "RTL-SDR watchdog: restarting rtlamr2mqtt (attempt {}/{})".format(
                attempt, self.max_restart_attempts
            ),
            "Gas meter stale with matching errors: {}. Restarting the add-on in {}s.".format(
                "; ".join(evidence), self.pre_action_delay
            ),
        )
        self.run_in(self._do_restart, self.pre_action_delay)

    def _do_restart(self, kwargs):
        if self.dry_run:
            self.log("rtlsdr_watchdog: [DRY RUN] would call hassio/addon_restart addon={}".format(
                self.addon_slug
            ))
        else:
            try:
                self.call_service("hassio/addon_restart", addon=self.addon_slug)
            except Exception as err:  # noqa: BLE001
                self.log(
                    "rtlsdr_watchdog: hassio/addon_restart failed, not counting this attempt: {}".format(err),
                    level="WARNING",
                )
                return

        self.state["restart_attempts"] = self.state.get("restart_attempts", 0) + 1
        self.state["last_restart_ts"] = self._now().isoformat()
        self._save_state()

    def _shutdown_stage(self, usb_fault, evidence):
        if not usb_fault:
            self._notify(
                "RTL-SDR watchdog: still failing after {} restarts".format(
                    self.max_restart_attempts
                ),
                "No USB-level fault confirmed (errors: {}). Not shutting down Proxmox.".format(
                    "; ".join(evidence)
                ),
                key="generic_only_exhausted",
            )
            return

        last_shutdown_ts = self._parse_ts(self.state.get("last_shutdown_ts"))
        if last_shutdown_ts is not None and (self._now() - last_shutdown_ts) < self.min_shutdown_interval:
            self._notify(
                "RTL-SDR watchdog: shutdown blocked by cooldown",
                "RTL-SDR fault persists but a Proxmox shutdown happened < {} ago.".format(
                    self.min_shutdown_interval
                ),
                key="shutdown_cooldown",
            )
            return

        if self.state.get("shutdown_pending_verification"):
            self._notify(
                "RTL-SDR watchdog: shutdown blocked, prior shutdown unverified",
                "A previous automatic shutdown hasn't been verified to fix the fault yet "
                "(no fresh reading seen since). Not shutting down again automatically - "
                "check the dongle/host and reset with the rtlsdr_watchdog_reset event.",
                key="shutdown_unverified",
            )
            return

        self.state["last_shutdown_ts"] = self._now().isoformat()
        self.state["shutdown_pending_verification"] = True
        if not self._save_state():
            # Persisting the lock failed - shutting down anyway would mean
            # a fresh boot loads the OLD state (no cooldown, no pending-
            # verification flag) and could auto-shutdown again immediately.
            # Refuse the destructive action instead.
            self.state["last_shutdown_ts"] = last_shutdown_ts.isoformat() if last_shutdown_ts else None
            self.state["shutdown_pending_verification"] = False
            self._notify(
                "RTL-SDR watchdog: shutdown aborted, safety lock not persisted",
                "Refusing to shut down Proxmox: the pending-verification/cooldown state "
                "could not be written to disk, and shutting down without it risks an "
                "unguarded repeat shutdown after power-on. Check the AppDaemon add-on's "
                "filesystem.",
                key="shutdown_state_write_failed",
            )
            return

        self._notify(
            "RTL-SDR watchdog: shutting down Proxmox host",
            "USB-level RTL-SDR fault persisted after {} add-on restarts (errors: {}). "
            "Shutting down the Proxmox host in {}s so the dongle can be power-cycled. "
            "Home Assistant will go offline - power the host back on manually.".format(
                self.max_restart_attempts, "; ".join(evidence), self.shutdown_notice_seconds
            ),
            key="shutdown",
        )
        self.run_in(self._do_proxmox_shutdown, self.shutdown_notice_seconds)

    def _do_proxmox_shutdown(self, kwargs):
        if self.dry_run:
            self.log("rtlsdr_watchdog: [DRY RUN] would call rest_command/proxmox_shutdown")
            return
        self.call_service("rest_command/proxmox_shutdown")
