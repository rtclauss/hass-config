# RTL-SDR / gas meter watchdog

`appdaemon/apps/rtlsdr_watchdog.py` (app `rtlsdr_watchdog`, class
`RtlSdrWatchdog`) watches the `rtlamr2mqtt` add-on (slug
`6713e36e_rtlamr2mqtt`), which reads the gas meter over an RTL-SDR USB dongle
passed through to the Proxmox VM running Home Assistant, and publishes
`sensor.raw_house_gas_meter_reading` / `sensor.raw_house_gas_meter_last_seen`
over MQTT.

## Why a power-cycle, not just a restart

A USB/kernel-level fault on the passed-through dongle can't always be cleared
by restarting the add-on container — sometimes only a full power-cycle of the
Proxmox host clears it. This watchdog tries the cheap fix first (restarting
the add-on) and only escalates to shutting down Proxmox
(`rest_command.proxmox_shutdown`, defined in `packages/zigbee_zwave.yaml`)
after that's been tried and failed repeatedly.

This mirrors two other watchdogs that can shut the same host down:
`appdaemon/apps/reboot.py` (reboots the HAOS host on LAN unreachability) and
`packages/z2m_lifecycle.yaml`'s `shutdown_proxmox_z2m_unavailable` automation
(restarts Zigbee2MQTT, then shuts down Proxmox). All three are independent,
with their own cooldowns.

## The two signals, and why both are required

A cycle only counts as "unhealthy" when **both** hold:

1. **Staleness** — no new gas-meter reading for `stale_after_minutes`
   (default 60; the add-on itself reads every ~10–20 min via
   `general.sleep_for: 600`). Computed as the *newest* of the reading
   sensor's `last_updated`, the last-seen sensor's `last_updated`, and the
   last-seen sensor's *state value* parsed as a timestamp — **not** the
   last-seen state value alone, which is the meter's own embedded timestamp
   and can look "stale" even when MQTT delivery is current.
2. **A known error pattern** in the add-on's own logs (fetched fresh each
   cycle — see "How logs are read" below).

Either alone is a no-op. So is anything the app can't verify — a missing
sensor, unreadable logs, no pattern match. This is deliberate: a broken probe
that always reports failure is exactly what caused `reboot.py`'s two
reboot-loop incidents (2026-09-01, 2026-09-08). An unhealthy result also has
to repeat for `confirm_cycles` (default 2) **consecutive** checks — any
clean or "can't tell" check in between resets the counter to zero.

## Pattern tiers

- **`USB_FAULT_PATTERNS`** — hard libusb/device-level strings
  (`usb_claim_interface error`, `No supported devices found`, `rtl_tcp:
  error`, etc.). A single occurrence is immediate USB-fault-tier evidence —
  this tier is what's allowed to eventually justify a Proxmox shutdown.
- **Death-loop burst** — the add-on already respawns its own `rtlamr`
  subprocess internally on death (`WARNING: rtlamr process died (exit code:
  N), attempting restart` — a real example seen live on 2026-09-24, caused
  by an i/o timeout talking to its local `rtl_tcp` on 127.0.0.1:1234).
  Supervisor's own add-on `watchdog: true` never sees this since the add-on
  container itself stays "started" throughout. A couple of these lines is
  normal jitter and is ignored entirely; `death_loop_min_count` or more
  occurrences (default 5) in one fetched log tail is promoted to a
  USB-fault-tier hit, on the theory that if the add-on's own retries aren't
  keeping it stable, only a power-cycle will.
- **`GENERIC_ERROR_PATTERNS`** — `Errno`, tracebacks, "Connection refused".
  These can justify restarting the add-on but can **never** justify a
  Proxmox shutdown on their own (e.g. `Errno 111` also fires when EMQX
  restarts, which has nothing to do with the USB dongle).

## The escalation ladder

1. **Notify** at every stage, before acting.
2. **Restart the add-on** (`hassio/addon_restart`) up to `max_restart_attempts`
   times (default 3). After each attempt, evaluation is suppressed for
   `restart_settle_minutes` (default 25, comfortably above the add-on's own
   read cycle) so the restarted container gets a real chance to read again.
   An attempt is only counted once `hassio/addon_restart` has actually been
   dispatched successfully — if the delayed callback is lost (e.g. an
   AppDaemon reload during `pre_action_delay_seconds`) or the service call
   raises, nothing is consumed and the next unhealthy cycle retries. This
   guarantees the host is never eligible for shutdown having had fewer than
   `max_restart_attempts` *real* restarts tried. The dispatch also
   revalidates both signals immediately beforehand (same as the shutdown
   dispatch below) — a genuine recovery, or the log evidence no longer
   matching, during `pre_action_delay_seconds` aborts the restart instead of
   disrupting an add-on that's already fine and burning a settle window for
   nothing.
3. **Shut down Proxmox** (`rest_command/proxmox_shutdown`) only once restart
   attempts are exhausted, and only when **all** of:
   - the evidence includes a USB-fault-tier hit (generic-only errors never
     shut down the host, they just stop the ladder with a notification);
   - at least `min_shutdown_interval_hours` (default 24) have passed since
     the last automatic shutdown;
   - no prior shutdown is still "pending verification" (see below).

**The fault is revalidated immediately before dispatch**, not just when it
was originally confirmed. `shutdown_notice_seconds` (default 60s) is a
deliberate window for the notification to go out, but it's also long enough
for a genuine reading to arrive in the meantime — `_do_proxmox_shutdown`
re-checks staleness right before calling `rest_command/proxmox_shutdown`,
and aborts (notifying instead) if the meter has recovered, or even if it's
merely become unreadable ("can't tell" is never license to proceed with a
destructive action). Without this, an avoidable Home Assistant outage could
happen purely because of timing, seconds after the fault had already
cleared itself.

A restart or shutdown is also refused if one of the same kind is **already
queued but hasn't fired yet** — tracked via `_pending_restart_handle`/
`_pending_shutdown_handle`. Without this, unusually short
`check_interval_minutes`/`confirm_cycles` combined with a long
`pre_action_delay_seconds`/`shutdown_notice_seconds` could let another
confirmed-unhealthy cycle land before the first delayed callback fires,
scheduling a second one and silently losing the ability to cancel the first
(a later `rtlsdr_watchdog_reset` could only cancel the newer timer).

Rough timing with the defaults: ~65 minutes to the first restart attempt (60
min stale + 2 checks 5 min apart), then up to 3×~25 minute settle windows —
so roughly 2.3 hours minimum before any shutdown is even possible, and only
then if the fault is USB-specific.

**Recovery**: any non-stale check clears `restart_attempts` and
`shutdown_pending_verification` (keeping `last_shutdown_ts` — the cooldown
still applies) and sends a "recovered" notification — but only once that
clear is confirmed **durably saved**. If persisting it fails, the in-memory
state is kept at its prior (cautious) values too, rather than diverging from
what's actually on disk: an AppDaemon reload before the underlying issue is
fixed must not silently regress to a stale "exhausted attempts" state that
would let a later, unrelated fault skip straight past the required restarts.
The clear is simply retried on the next non-stale cycle.

## The loop-breaker: shutdown-pending-verification

Unlike `reboot.py`, a Proxmox shutdown sets
`shutdown_pending_verification = true` in the persisted state file. That flag
blocks **any further automatic shutdown**, even after the cooldown expires,
until a fresh reading is actually seen. A power-cycle that didn't fix the
fault can never trigger a second automatic shutdown by itself — a human has
to look at it.

This flag is only set once the shutdown has actually been dispatched — never
before. Deciding to shut down, notifying, and scheduling the delayed action
happen first; only the delayed callback itself, after a successful (or
dry-run-simulated) `rest_command/proxmox_shutdown` call, marks the state. If
that callback were ever lost (an AppDaemon reload during
`shutdown_notice_seconds`) or the service call raised, pre-marking state
would wedge the watchdog permanently "pending verification" for a shutdown
that never happened — with no fresh reading ever coming (the fault is real)
and no automatic way out but a manual reset. The same ordering applies to
counting a restart attempt against `max_restart_attempts`.

**Clearing the lock requires a genuine meter reading, not just fresh
metadata.** When Home Assistant boots after the Proxmox power-cycle, its MQTT
integration can restore or replay retained state, which bumps the reading/
last-seen entities' `last_updated` without the meter having actually
produced anything new — making a still-broken dongle briefly look "fresh" by
delivery metadata alone. So the general staleness check (used everywhere
else, including ordinary restart-only recovery) is not trusted here: clearing
`shutdown_pending_verification` specifically requires the last-seen entity's
own **state value** (the meter's self-reported reading timestamp, embedded in
the payload — immune to replay, since a replayed retained message still
carries its original embedded timestamp) to be strictly newer than
`last_shutdown_ts`. Until that's true, the watchdog stays "pending
verification" even if the sensors otherwise look fresh.

## State and resetting it

Persisted as JSON in `appdaemon/apps/.rtlsdr_watchdog_state.json`
(`restart_attempts`, `last_restart_ts`, `last_shutdown_ts`,
`shutdown_pending_verification`) so counters survive an AppDaemon restart.
This file (and its `.tmp` write-buffer, below) is excluded from
`scripts/appdaemon_sync.py`'s pull/push (see `RSYNC_EXCLUDES`) — it's
live-only state, never checked in or copied around.

**Writes are atomic** (write to `.rtlsdr_watchdog_state.json.tmp`, `fsync`,
then `os.replace` onto the real file), not an in-place truncating write.
This matters specifically because the shutdown state is saved *after*
dispatching the actual host shutdown (see above) — if the write were a
plain in-place overwrite and the process (or the Proxmox host itself, which
this app just told to power off) died mid-write, the file could be left
empty or partial, and `_load_state()` would silently treat that corruption
as "no state," discarding the very lock this app exists to protect. With
atomic replace, a reader only ever sees the fully-written old file or the
fully-written new one, never a half-written one.

**In dry-run, state changes are never written to this file.** The ladder
still progresses in memory within a single dry-run session (so you can watch
a full notify → restart → shutdown sequence play out in the logs/
notifications), but nothing is persisted. This is deliberate: if simulated
restart/shutdown counters were saved to disk, the moment you flipped
`dry_run: false` the app would load state showing restarts already exhausted
(or a shutdown already "pending verification") and refuse to take the real
action it was just armed to take. Flipping `dry_run: false` always starts the
real ladder from a clean slate.

If persisting the shutdown-pending-verification lock ever fails after the
shutdown has already been dispatched (e.g. a read-only or full filesystem),
there is no "abort" option left — the app logs at `ERROR` and sends a
best-effort notification instead, since the residual risk (a disk write
failing at that exact instant) is far smaller than the risk pre-marking
state would reintroduce.

Firing `rtlsdr_watchdog_reset` also **cancels any restart or shutdown that's
already been scheduled but hasn't fired yet** (AppDaemon's `run_in` timer
handle is tracked and cancelled). Without this, resetting state right after
fixing the dongle by hand — while a shutdown notice is still counting down —
would clear the safety lock without stopping the queued shutdown, so the
host would still go down, and after boot nothing would block a further
automatic shutdown either.

**If that cancellation can't be confirmed, the reset itself is refused** (and
notified) rather than proceeding anyway. An unconfirmed cancellation means
the queued action may have already fired — in which case the state it just
legitimately set (a real dispatched shutdown's cooldown/lock) must not be
wiped — or may still be about to fire, in which case clearing the lock now
would leave it unguarded. Either way, wiping state on an uncertain
cancellation is unsafe, so `_manual_reset` requires every pending action to
be confirmed cancelled before it touches state at all. Check whether the
add-on restarted or the host is shutting down before retrying the reset.
"Confirmed cancelled" means AppDaemon's `cancel_timer` neither raised nor
returned `False` — a `False` return (no exception, but the timer couldn't be
cancelled, e.g. its callback was already running) is treated exactly like a
raised exception, not silently as success.

If the reset itself is allowed to proceed but the resulting default state
fails to write to disk (e.g. read-only/full filesystem), the in-memory reset
still happens — which is fail-safe on its own, since an AppDaemon reload
before the underlying issue is fixed reverts to the *old*, more-cautious
state, never a less-cautious one — but the app notifies that the reset did
not persist, rather than reporting a clean reset that silently isn't
durable.

To clear state by hand after a manual fix, fire the `rtlsdr_watchdog_reset`
event from Developer Tools → Actions (or delete the state file directly on
the add-on's filesystem).

## How logs are read

There's no `hassio.addon_stdout`/log-read *service* — Supervisor exposes
logs only over its REST API. The AppDaemon add-on's own permissions are
`hassio_api: false` / `hassio_role: default`, so it can't call the raw
Supervisor API for another add-on's logs directly. Instead it goes through
Core's hassio proxy (`homeassistant_api: true` gives it that), using the same
`SUPERVISOR_TOKEN` env var already used for the AppDaemon HASS plugin:

```
GET http://supervisor/core/api/hassio/addons/6713e36e_rtlamr2mqtt/logs
Authorization: Bearer $SUPERVISOR_TOKEN
```

If that route ever gets refused (401/403), set `ha_token` in `apps.yaml` to
an admin long-lived access token stored in gitignored `secrets.yaml`
(`rtlsdr_watchdog_ha_token` — never commit the value). Setting `ha_token`
alone is enough: the app automatically switches `logs_url` to
`http://homeassistant:8123/api/hassio/addons/<slug>/logs` (the Supervisor
proxy route only accepts `SUPERVISOR_TOKEN`, not an HA access token) — no
need to also set `logs_url` by hand, unless you want to override it to
something else entirely, which always takes precedence. Any fetch failure
(timeout, non-200, network error) is treated as "can't tell" — a no-op,
never an escalation.

Log evidence is also time-correlated to the current outage: only lines
timestamped after the last known-good reading count as evidence (parsing
both the wrapper script's local-time bracket timestamps and the `rtlamr`
binary's own tz-aware `time=...` lines). Without this, a USB error line that
scrolled into view during an earlier, already-recovered outage could sit in
the fetched tail and keep matching on a later, unrelated stale period.

## Tuning

All thresholds are `apps.yaml` args under the `rtlsdr_watchdog:` entry — see
that file for the full list with current values and inline comments. The
notable ones: `dry_run`, `stale_after_minutes`, `confirm_cycles`,
`death_loop_min_count`, `max_restart_attempts`, `restart_settle_minutes`,
`min_shutdown_interval_hours`.

## Dry-run → live

The app ships with `dry_run: true`. In dry-run it walks the full decision and
escalation ladder and notifies at every stage (titles prefixed `[DRY RUN]`),
but never calls `hassio/addon_restart` or `rest_command/proxmox_shutdown`.
Only flip `dry_run: false` in `apps.yaml` after watching real dry-run
notifications for a while — ideally through at least one real fault, given
the gas meter has already shown this failure mode live. Leave
`min_shutdown_interval_hours` and the pending-verification lock in place
regardless; they're the safety net once it's live.

Testing: `tests/test_appdaemon_rtlsdr_watchdog.py` covers the pattern
matching, staleness math, the AND/debounce decision logic, the escalation
ladder ordering, shutdown gating, dry-run behavior, and state persistence.
Run with `uv run --with pytest pytest`.
