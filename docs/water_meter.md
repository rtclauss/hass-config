# Water Meter Reader

Replaces an earlier ESP32-CAM / "AI-on-the-edge" attempt that proved too
buggy to trust. This is the source of truth for the Raspberry Pi water meter
reader: hardware, architecture, MQTT contract, and the manual deployment
runbook. Keep it current before changing `water_meter/`, `packages/water_meter.yaml`,
or `deploy/systemd/water-meter-reader.*`.

## Hardware

- Meter: Mueller Systems 3/4" S encoder register, 8D Standard, IP68. Totalizer
  in gallons + flow in gpm on a dim/reflective display that needs angled light
  to read.
- Location: indoors, conditioned space, mains power nearby - no weatherproofing
  or battery/duty-cycling needed.
- Raspberry Pi 4 Model B, running Ubuntu 26.04 LTS - headless, no desktop
  needed. (Originally a Pi 3B+ on Raspberry Pi OS Lite; replaced 2026-09-20.)
- A USB webcam (Logitech C270) and an existing Zigbee bulb (already paired
  to zigbee2mqtt), mounted in a fixed jig in front of the meter's display
  window. Offset the light ~30-45 degrees from the camera axis (not
  coaxial) to avoid glare. Captured at **1280x960** (see "Capture
  resolution" below) - the camera supports this in both YUYV and MJPG at
  full 30fps (`v4l2-ctl --list-formats-ext`).

## Architecture

```text
systemd timer (every ~10 min; a run can take up to ~18 min in the worst case
                below, in which case the *next* tick is a safe no-op - see
                "Vision-LLM fallback")
  -> water_meter.reader (on the Pi)
       -> publish light ON straight to the zigbee2mqtt broker
       -> capture a frame (webcam), publish light OFF
       -> crop to the calibrated ROI / digit boxes
       -> OCR: ssocr (primary, fast) -> vision LLM (qwen2.5vl via Ollama,
          optional, 6-shot prompted, reads through glare) -> OpenCV template
          match (last resort, fully offline)
       -> sanity gate: numeric, right digit count, non-decreasing, plausible delta
       -> if rejected for "value decreased" / "implausible jump" and the
          vision LLM is configured: one requery of the LLM on the same
          image, with the suspect value as context, before giving up
       -> publish reading + status + MQTT discovery config
  -> Home Assistant (packages/water_meter.yaml)
       -> sensor.water_meter (via MQTT discovery, device_class: water, total_increasing)
       -> sensor.water_meter_status / sensor.water_meter_last_reading_time (mqtt sensors)
       -> sensor.water_meter_reading_age (template) -> stale-reading alert automation
```

The capture loop talks directly to the MQTT broker for light control and
publishing - it does not depend on Home Assistant being up to do its job.

Design choices made specifically to avoid repeating the ESP32-CAM experience:

- **Fixed jig, no drift** - ROI and digit boxes are calibrated once as pixel
  coordinates; no autofocus hunting or perspective correction at runtime.
- **Deterministic OCR, not ML** - `ssocr` (seven-segment OCR) against a
  segmented digit display is a solved, offline-debuggable problem. Any saved
  image in `images/history/` or `images/rejects/` can be re-run through it by
  hand.
- **Gate bad reads before they reach HA** - a rejected read is never
  published as the sensor value, so `state_class: total_increasing` history
  never gets corrupted by a garbage OCR result.
- **General-purpose Linux** - SSH in, read `journalctl`, look at the saved
  images - much easier to debug in place than ESP32 firmware.
- **Self-healing camera watchdog** - the bench-tested webcam's V4L2/GStreamer
  backend has been observed to wedge (every read times out, even from a
  freshly opened capture in a brand-new process) in a way that only a host
  reboot clears. `water_meter/watchdog.py` tracks consecutive capture
  failures across runs and reboots the host once they cross
  `WATER_METER_CAPTURE_FAILURE_REBOOT_THRESHOLD` (default 2), rather than
  silently erroring every cycle until a human notices and reboots it by hand.

### Capture resolution

`cv2.VideoCapture(device)` doesn't request a resolution, so V4L2 was
silently defaulting to 640x480 - the lowest common UVC mode - even though
this camera supports up to 1280x960 (confirmed via `v4l2-ctl
--list-formats-ext`; both YUYV and MJPG hit full 30fps at that size).
`capture.grab_stable_frame` now explicitly requests `CalibrationConfig.
capture_width`/`capture_height` (default 1280x960 for a fresh calibration -
see `DEFAULT_CAPTURE_WIDTH`/`DEFAULT_CAPTURE_HEIGHT` in `config.py`) and
switches to MJPG to get there.

This mattered for real: a 2026-09-28 incident needed the *full raw frame*,
not the tiny ~142x32 calibrated ROI crop, to visually resolve a 0/8 digit
confusion the VLM kept misreading identically across 8 consecutive polls -
the crop simply didn't have enough real pixels in it at 640x480 for that
specific digit pattern.

**Existing `calibration.json` files drawn against 640x480 must have every
pixel coordinate (`roi`, every `digit_boxes` entry) multiplied by the same
scale factor as the resolution change**, or the boxes will land in the
wrong place on the now-larger frame. This project's own move was a clean
2x in both dimensions (640x480 -> 1280x960), so every coordinate was simply
doubled - no interactive recalibration needed, since doubling preserves the
same physical field of view exactly. A non-integer or non-uniform
resolution change would need a real recalibration pass instead (`calibrate
capture-only` + `calibrate` - see the runbook below).
`CalibrationConfig.capture_width`/`capture_height` default to the *old*
640x480 (not the new defaults) specifically so an existing calibration.json
without these fields doesn't silently start capturing at the wrong
resolution for its own box coordinates.

### Light brightness

Bench-tested against the real jig: 100% brightness glares directly off the
meter's LCD and blows the digits out completely; 60% and 80% both read
cleanly. `WATER_METER_LIGHT_BRIGHTNESS` defaults to 204/254 (~80%) for
margin against ambient light changes. This bulb (Hue White A19) has no
`color_temp` support - brightness is the only tunable.

### The register cycles display fields on light pulses

Confirmed on the real hardware: this AMR encoder register advances to a
different display field (gallons totalizer -> gpm flow rate -> at least one
diagnostic screen) each time its light sensor sees a rising edge, and
reverts back to the totalizer after enough idle (dark) time. A single
on -> wait -> capture -> off cycle every `OnUnitActiveSec` (10 minutes by
default) stays well past that idle window, so production runs land on the
totalizer reliably; captures taken in rapid succession (seconds apart) can
catch it mid-cycle instead. The sanity gate's digit-count/numeric checks
already reject a caught-mid-cycle read (e.g. `0.00` or a diagnostic code)
before it can reach HA, so this is a display-cycling quirk to be aware of
during manual testing, not a production risk.

### Decimal point

Confirmed against real captures: this meter's display has a fixed decimal
point before its final digit - the raw OCR read `02138978` is actually
`213897.8` gallons, not `2138978`. `calibration.json`'s `decimal_places`
(here: `1`) tells `sanity.validate_reading` to divide the raw digit-string
integer by `10 ** decimal_places` before any gating or publishing; a meter
with no decimal point should leave this at its default of `0`.

### The implausible-jump gate scales with elapsed time

`max_gallons_per_interval` is a *rate* cap (plausible usage per
`nominal_interval_seconds`, default `600` to match the timer's
`OnUnitActiveSec`), not a flat ceiling on the delta since the last accepted
reading. `sanity.validate_reading` scales the allowance by how many nominal
intervals have actually elapsed since `last_good.timestamp`. This matters
whenever a poll is skipped or rejected (a watchdog reboot, a run of OCR
failures): the real delta since the last *accepted* reading keeps growing
across every missed interval, and comparing it against a limit sized for a
single interval would reject it forever, since `last_good` never advances -
every subsequent reading looks like an even bigger "jump" against an
increasingly stale baseline. Elapsed time under one nominal interval still
gets the full single-interval allowance (never scaled down), matching the
original behavior for the common on-time case.

**`max_sustained_gallons_per_hour` caps how far that scaling can grow.**
A real incident (2026-09-27) showed the fully-linear version of this
scaling let a ~4,500-gallon misread through as "plausible" after a
~19-hour gap, because the allowance had scaled up to 28,500 gallons by
then - no household sustains anywhere near peak burst flow for that long.
The first `nominal_interval_seconds` still gets the full
`max_gallons_per_interval` burst allowance (real bursty multi-fixture
usage), but every second beyond that is capped at this much lower
sustained rate (`DEFAULT_MAX_SUSTAINED_GALLONS_PER_HOUR` = 600 gal/hour =
10 GPM - chosen to comfortably cover a real leak, a heavy irrigation day,
or filling a pool, while still bounding how far one bad read can be masked
by a long gap). This is a defense-in-depth complement to the leading-digit
cross-check above, not a replacement for it - it wouldn't have caught the
2026-09-27 incident by itself (4,500 gallons was still under even this
tighter cap over that particular gap length), but it meaningfully narrows
the window for *other* misreads, especially ones landing outside the
glare-protected positions that the cross-check can't fix.

### `stuck_after_hours` actually controls the stuck window

`stuck_after_hours` is converted to a sample count via
`nominal_interval_seconds` and used directly as the "same value for this
many consecutive readings" window `sanity.validate_reading` checks before
setting `stuck=True`. It's independent of `history_limit`, which separately
just bounds how much history is *stored* (shared with `reader.py`'s
image-history rotation) - so `stuck_after_hours` can only be honored up to
whatever `history_limit` allows to be retained. Configure `history_limit`
generously enough to cover the stuck window you actually want (the
defaults, 200 samples at the default 600s interval, comfortably cover the
default 24-hour window).

## Vision-LLM fallback (optional)

`ssocr` and the OpenCV template matcher both classify one digit at a time -
neither can recover a digit under a fixed glare streak, because the glare
genuinely destroys the pixel data there rather than just adding noise no
amount of thresholding/morphology fixes. A vision LLM reads the display
holistically instead, and has been confirmed (against real captures of this
meter) to correctly read digits under that same glare. This tier is entirely
optional and off by default - a deployment with no Ollama host configured
gets the original ssocr-then-template behavior, unchanged.

**How it's wired** (`water_meter/ocr.py`):

- `read_digits()` tries `run_ssocr()`, then - only if `vlm_host` is set -
  `read_digits_vlm()`, then falls back to `match_digits()` (the template
  matcher) if both of those fail or aren't configured.
- `read_digits_vlm()` POSTs the crop image (base64-encoded JPEG) to an
  Ollama `/api/generate` endpoint with `stream: false`. It deliberately does
  **not** cap `num_predict` - an earlier attempt at bounding the model's
  "thinking" trace with a small token budget risked truncating the answer
  before it was actually emitted. A generous request timeout is the safer
  knob; see below.
- The prompt is **6-shot, not zero-shot**: `VLM_FEWSHOT_EXAMPLES` bundles 6
  real captures of this exact display (`water_meter/vlm_examples/*.jpg`),
  each with its true reading confirmed by direct visual inspection, sent
  ahead of the actual query image on every call. This was switched from a
  plain zero-shot prompt on 2026-09-20 after a head-to-head comparison
  (see the "Reading Through Glare" report) found that just wording the
  zero-shot prompt more strictly made accuracy *worse*, not better, while
  showing the model real labeled examples of this exact display's glare
  pattern took `qwen2.5vl:7b` from 33% to 100% exact-match on captures it
  had never seen. The 6 example readings are anchored to the meter's
  current `02141xxx.x` value range and will need refreshing once the
  leading digits roll over past `021`.
- The prompt also names the glare failure mode explicitly (added
  2026-09-27, after the leading-digit misread incident above): it tells the
  model the leftmost 2-3 digits are often glare-crossed and change
  extremely rarely, unlike the digits further right. This is domain/visual
  grounding, not an output-format rule - deliberately different from the
  "answer with exactly N digits" strictness that was tried and made things
  worse (see the same report). Tested against the 16-capture ground-truth
  set with no regression (still 16/16 exact-match) before adopting.

**Latency was real and highly variable**, not just slow, back when the
Ollama host ran CPU-only: one measured call took 123.9s total, of which only
48.4s was actual token generation - Ollama's own timing fields
(`eval_duration`, `prompt_eval_duration`, `load_duration`) didn't account
for the rest, which looked like host-level contention rather than anything
about the model itself. `DEFAULT_VLM_TIMEOUT` (480s) and the systemd unit's
`WATER_METER_VLM_TIMEOUT_SECONDS` were both raised after a live run hit a
shorter (240s) timeout, then the same generation was observed (via
`/api/ps`) to keep running server-side and complete anyway - a timeout that
short was silently throwing away calls that would have succeeded. The
timeout stays at 480s even now that the host has a GPU (see below) - both as
margin for occasional slow calls and because this box has had repeated
unrelated Ollama outages (service restarts, updates).

**`options.num_thread` is capped at `DEFAULT_VLM_NUM_THREAD` (2)** in every
`read_digits_vlm` call. An RTX 2000 Ada was added to the Ollama host to run
the VLM GPU-resident, which dropped typical call latency from 100-600s+
down to single-digit seconds - but GPU offload doesn't cover image
preprocessing/tokenization, and Ollama defaults to using every CPU core for
that remaining work. That default was enough to re-trigger the box's CPU
thermal alarm even with inference itself fast and GPU-bound. Capping
threads trades a little of that CPU-side latency for not cooking the box.

**`options.num_ctx` is raised to `DEFAULT_VLM_NUM_CTX` (16384)**. Ollama
defaults every model's context to 4096 tokens regardless of what the model
itself supports, and the 6-shot prompt sends 7 images per call (6 examples
+ the query crop) - the first attempt at this hit a hard 400
`exceed_context_size_error` (5 images alone was already 5427 tokens).
16384 gives real headroom above what 7 small images plus prompt text
actually need.

**Leading-digit cross-check, run on every reading, not just rejected ones**
(`water_meter/reader.py`, `_correct_glare_positions_from_last_good`):
`calibration.low_confidence_ok_indexes` marks the meter's highest-place-
value digits (millions/hundred-thousands) - positions under a fixed glare
streak no OCR method here has ever read reliably. Those positions physically
can't change except once every tens of thousands of gallons, far slower than
any realistic per-poll delta, so `last_good`'s own digits there are a
strictly better source of truth than a fresh read of a spot the glare
genuinely destroys.

This used to only run after a "value decreased"/"implausible jump"
rejection - but a real incident (2026-09-27) showed that's not enough: a
misread on exactly one of these positions can still slip straight past the
plausibility gate on the *first* try whenever enough time has elapsed since
`last_good` that the time-scaled jump allowance (see `sanity.py` below) is
generous, so self-heal never got a chance to run because nothing had
failed yet. The cross-check now always compares the raw read against
`last_good`'s digits at these positions, regardless of whether the raw
reading was already accepted:
- positions agree -> no-op, whatever the raw validation result was stands.
- positions disagree and the corrected candidate validates -> use the
  corrected candidate (this is what catches the 2026-09-27 case: an
  accepted-but-wrong value gets corrected before it's ever saved as the
  new `last_good`).
- positions disagree and the corrected candidate does *not* validate ->
  ambiguous (could be a genuine rollover into a new highest-place-value
  digit, or a different, deeper misread) - never silently trust either
  digit string; this now produces a `"leading-digit mismatch: ..."`
  rejection so the VLM-requery fallback below gets an independent look
  before anything is accepted.

**Automatic requery on a suspicious value** (`water_meter/reader.py`,
`_requery_vlm_on_suspect_value`): tried next, if the cross-check above
didn't resolve it or no glare positions are configured. "value decreased",
"implausible jump", and "leading-digit mismatch" all mean the digits parsed
cleanly but the resulting value looks wrong - the signature of a single
misread digit (confirmed live: even the VLM occasionally flips the
glare-affected leading digit), not a garbled read. Since the meter hasn't
moved between the first attempt and now, one extra VLM call against the
*same* crop - with the suspect value and the last confirmed reading given
as context - gets a second, better-informed answer instead of discarding
the whole capture. This fires at most once per run and only for those
three rejection reasons; a bad digit count, a non-numeric read, or an
outright capture/OCR failure means there's nothing a requery of the same
image would fix.

Because a single run can now involve two full VLM calls back-to-back (the
initial attempt plus one requery), `deploy/systemd/water-meter-reader.service`
sets `TimeoutStartSec=1080` - roughly 2x `WATER_METER_VLM_TIMEOUT_SECONDS`
plus capture/ssocr/publish overhead. If a run genuinely takes that long,
systemd simply won't start a second overlapping instance of the still-active
oneshot unit when the next 10-minute tick fires - that tick is a no-op, not
an overlap or a crash.

**Bootstrap reads require the VLM to agree with itself.** The VLM has no
numeric confidence signal to gate on the way the template matcher does, and
has been confirmed live to occasionally misread the same glare-affected
digit. That's an acceptable risk on an ordinary run (the decrease/
implausible-jump sanity checks are the backstop), but the read that
*establishes* `last_good_reading.json` has no backstop - a wrong bootstrap
seed silently blocks every correct reading after it as an "implausible
jump" forever. So while bootstrapping, `read_digits` calls the VLM twice on
the same image and only trusts it if both calls return the identical digit
string; a disagreement falls through to template matching instead (which
does enforce full confidence on bootstrap - see `match_digits`).

**To enable**, add to `deploy/systemd/water-meter-reader.service` (or any
`EnvironmentFile`):

```ini
Environment=WATER_METER_VLM_HOST=<ollama-host>:<port>
Environment=WATER_METER_VLM_MODEL=qwen2.5vl:7b
Environment=WATER_METER_VLM_TIMEOUT_SECONDS=480
```

Use a static IP for `WATER_METER_VLM_HOST`, not a `.local` mDNS name - the
same mDNS flakiness that forced `WATER_METER_MQTT_HOST` to a static IP (see
the comment above `Environment=WATER_METER_MQTT_HOST=` in
`deploy/systemd/water-meter-reader.service`) was reproduced against the
Ollama host too (1 of 3 lookups failed in testing from this Pi).

**Known limitation**: the VLM is a real improvement, not a perfect fix - it
has been observed to occasionally misread the same glare-affected leading
digit (e.g. `0` read as `8`). The sanity gate and requery reduce how often
that reaches a human, and a bad VLM read is usually safely *rejected*
outright rather than accepted - but not always: a real incident (2026-09-27)
saw a misread slip past the plausibility gate because a long gap since
`last_good` made its time-scaled allowance generous. See "The leading-digit
cross-check" above and "sustained-rate cap" below for the hardening that
followed, and "Human-in-the-loop notifications" below for the human
backstop on whatever's left.

## Human-in-the-loop notifications

When a rejected reading can't be automatically resolved - self-heal's
leading-digit cross-check *and* the VLM requery both fail (`reader.py`'s
`_notify_ha_of_unresolved_reading`) - the reader sends an actionable
notification to Home Assistant instead of just logging a rejection. This is
the lightweight, real-time version of GitHub issue #1057's "manual
digit-crop review tool" idea, built on infrastructure that already exists
(the owner's phone) rather than a new web app. It only fires for "value
decreased"/"implausible jump"/"leading-digit mismatch" - reasons where the
digits parsed cleanly but the *value* looked wrong, exactly the ambiguity a
human glancing at the crop can resolve in seconds. A hard OCR failure (bad
digit count, non-numeric) has no suggested value to approve, so nothing is
sent for those.

The notification carries three actions:
- **Approve** - accept the rejected value as correct.
- **Reject** - discard it, no change (`last_good` stays as-is).
- **Modify** - set `input_number.water_meter_manual_correction` in HA to the
  correct value; a separate automation applies it automatically.

**Why a second, persistent service is needed.** `water_meter/reader.py` is a
one-shot systemd-timer job that has already exited by the time a human
responds - minutes or hours later. `water_meter/correction_listener.py`
(`deploy/systemd/water-meter-correction-listener.service`, `Restart=always`)
is a small stdlib-only HTTP server that stays up to receive that response: a
Home Assistant automation (`packages/water_meter.yaml`) POSTs the approved/
corrected value to it, and it writes `last_good_reading.json` *and*
republishes the retained MQTT topics - both need updating, or the next
scheduled read would still compare against the stale local baseline even
after the visible sensor looked fixed.

The listener deliberately trusts the human's value outright, including a
*decrease* from the current `last_good` - overriding the reader's own
monotonic-increase safety net is the entire point. It exists specifically
to fix the case where `last_good` itself is the wrong (too-high) value,
which is exactly what happened on 2026-09-27 and needed a manual SSH fix
before this existed.

**Setup** (three secrets, none of them committed to git):
1. A Home Assistant long-lived access token (Profile -> Security ->
   Long-lived access tokens) - set as `WATER_METER_HA_TOKEN` in the Pi's
   `/etc/water-meter/credentials.env`. Lets `reader.py` call
   `notify.<WATER_METER_HA_NOTIFY_SERVICE>` (see
   `deploy/systemd/water-meter-reader.service` for the URL/service name).
2. Any long random string, invented by the user - set as
   `WATER_METER_CORRECTION_TOKEN` in the same credentials.env, *and* as the
   `water_meter_correction_token` secret (prefixed `Bearer `) in HA's own
   `secrets.yaml`. The listener refuses to start without this set - see
   `correction_listener.main`.
3. `water_meter_correction_url` in HA's `secrets.yaml`:
   `http://<pi-ip-or-hostname>:8091/correction`.

Enable the listener service on the Pi with:

```bash
sudo cp deploy/systemd/water-meter-correction-listener.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now water-meter-correction-listener.service
```

## MQTT contract

| Purpose | Topic | Payload |
| --- | --- | --- |
| Light control (direct to z2m) | `zigbee2mqtt/Basement/Water Meter Hue/set` | `{"state":"ON"}` / `{"state":"OFF"}` |
| Reading | `waterreader/sensor/water_meter/state` | plain number, gallons |
| Last successful read time | `waterreader/sensor/water_meter/last_reading_time` | ISO 8601 |
| Run status/health | `waterreader/sensor/water_meter/status` | `ok` / `error:<reason>` |
| HA discovery config (published by the Pi) | `homeassistant/sensor/water_meter/config` | discovery JSON, retained |

The light's friendly_name (`Basement/Water Meter Hue`) contains a literal `/`
and a space - both are valid MQTT topic-level characters, so the topic above
is used verbatim, matching `WATER_METER_LIGHT_TOPIC` in
`deploy/systemd/water-meter-reader.service`.

The discovery payload (`reader.discovery_payload`) includes `device` and
`origin` blocks - confirmed against the current MQTT discovery docs, these
are what group the entity under a real device in HA's registry and MQTT
integration page instead of it showing as an orphan entity. No `icon` field
is needed: `device_class: water` already gives the frontend a water-drop
icon automatically.

**Deliberately no `availability_topic`.** An earlier version of the
discovery payload set `availability_topic` to the status topic with
`payload_available: "ok"`, meaning HA marked `sensor.water_meter` fully
"Unavailable" on every routine OCR rejection - even though the last
accepted value in `state_topic` was still valid and unchanged. This reader
is a one-shot systemd timer job, not a persistent MQTT client, so there's
no real connection to back a Last Will/Testament-style availability signal
in the first place. Staleness is already surfaced by the dedicated
`sensor.water_meter_status` and `sensor.water_meter_reading_age` entities
(see the stuck-reading note below), so the main sensor just keeps showing
its last retained value.

**A stuck reading publishes `error:<reason>`, not `ok`.** A frozen camera or
OCR pipeline that keeps returning the same value is technically `accepted`
(the value itself is real and hasn't decreased or jumped implausibly), but
`packages/water_meter.yaml`'s staleness automation only alerts on
`sensor.water_meter_reading_age` or a status starting with `error` - and
`last_reading_time` keeps advancing on every accepted run, stuck or not, so
`reading_age` never grows either. Reusing the `error:` prefix for a stuck
status is what makes `sanity.validate_reading`'s stuck-reading detection
(the `stuck` field on its result, driven by `stuck_after_hours`/
`history_limit`) actually reach that automation instead of looking
perfectly healthy indefinitely.

## Known hardware issue: webcam USB lockups (Pi 3B+ era; hardware since replaced)

Bench-tested on a **Raspberry Pi 3 Model B Plus**: the webcam has been
observed to wedge after a handful of captures (every subsequent
`cv2.VideoCapture` read times out with `V4L2: select() timeout`, even from a
freshly opened capture in a brand-new process) in a way that only a host
reboot clears - `water_meter/watchdog.py` (see above) auto-recovers this,
but the root cause was root-caused to a genuine `dwc2` USB-controller
hardware/driver limitation specific to that board (BCM2837B0 has no separate
XHCI controller for any USB port).

**The Pi was physically replaced with a Raspberry Pi 4 Model B (Ubuntu
26.04) on 2026-09-20**, which has a proper XHCI controller (via a separate
VL805 chip) for all USB-A ports, making the dwc2 bug moot. The watchdog
mitigation is left in place regardless (cheap insurance, and it did still
fire intermittently for about a day right after the migration before
settling down - see the daily reboot section below).

## Daily preventive reboot

`deploy/systemd/water-meter-daily-reboot.service` / `.timer` reboots the Pi
roughly once a day (`OnBootSec=24h`, `OnUnitActiveSec=24h` - monotonic,
**not** `OnCalendar`, see below for why). This is not a targeted fix for
anything specific - the camera-stuck watchdog already self-heals that
failure mode on its own - just standard preventive hygiene for an always-on
embedded box (clears slow memory/fd leaks, refreshes the DHCP lease, applies
pending kernel/driver updates that need a reboot). A one-shot
`water-meter-reader.service` run that gets interrupted mid-cycle by the
reboot just means one skipped/late reading, not corruption.

**Why monotonic, not `OnCalendar=*-*-* 03:00:00`:** this Pi has no
battery-backed RTC, so every boot starts with a stale pre-NTP clock
(observed defaulting to `2026-07-27`, the firmware build date) until NTP
corrects it. An `OnCalendar` timer computes its "next fire" deadline using
whatever clock is active when it starts - when NTP later jumps the clock
forward by weeks/months in one step, that deadline is suddenly in the past
relative to corrected time, so systemd fires it immediately. This caused
**two separate real incidents** (2026-09-23 and -24), both requiring a
manual power cycle to break a ~50-second reboot loop: the first with
`Persistent=true` (explicit "missed run" catch-up), the second showing that
removing `Persistent=true` alone wasn't sufficient - the same clock-jump
race fires the timer regardless. `OnBootSec`/`OnUnitActiveSec` are computed
relative to elapsed monotonic time since boot, never wall-clock time,
which sidesteps this whole class of bug - the same pattern
`water-meter-reader.timer` already uses. Trade-off: reboots land at a
rolling time instead of a fixed 3am, which is a fine price for never
re-hitting this.

Enable on the Pi with:

```bash
sudo cp deploy/systemd/water-meter-daily-reboot.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now water-meter-daily-reboot.timer
```

## Repository layout

- `water_meter/` - the Pi-side Python package (deployed by cloning/pulling
  this whole repo to `/opt/hass-config` on the Pi, matching the
  `inky_display/` convention):
  - `config.py` - `ConnectionConfig` (env-sourced: MQTT/camera/paths) and
    `CalibrationConfig` (YAML-sourced: ROI, digit boxes, thresholds).
  - `capture.py` - webcam capture (`cv2.VideoCapture`) and direct MQTT light
    control.
  - `ocr.py` - `ssocr` subprocess wrapper; optional vision-LLM fallback
    (`read_digits_vlm`, via an Ollama HTTP API - see "Vision-LLM fallback"
    above) for the digits ssocr can't read; OpenCV template-match last
    resort (`load_digit_templates`/`match_digits`) for non-clean-7-segment
    digits or whenever the LLM is unavailable/unconfigured. `read_digits`
    validates ssocr's output (right digit count, all-numeric) before
    trusting it - an exit-0-but-malformed result (a partial read, stray
    characters) falls through to the VLM/template-match tiers just like an
    outright ssocr failure would, instead of skipping them and letting
    `sanity.validate_reading` reject a case the fallbacks could have
    actually read.
  - `sanity.py` - the validation gate: numeric/digit-count/non-decreasing/
    max-delta checks, last-good-value persistence, stuck-reading detection.
  - `reader.py` - orchestrates one run (including the vision-LLM requery on
    a suspicious value - see above); `python3 -m water_meter.reader` is the
    systemd `ExecStart`.
  - `watchdog.py` - tracks consecutive capture failures across runs and
    reboots the host once they cross a threshold (see "Known hardware
    issue" below).
  - `calibrate.py` - `capture-only` (run on the Pi) and `calibrate` (run on a
    workstation with a display, using `cv2.selectROI`) subcommands.
  - `correction_listener.py` - the persistent HTTP listener behind
    "Human-in-the-loop notifications" above; `python3 -m
    water_meter.correction_listener` is its systemd `ExecStart`.
- `deploy/systemd/water-meter-reader.service` / `.timer` - the oneshot
  service + timer, mirroring `deploy/systemd/inky-owner-suite.service`.
- `deploy/systemd/water-meter-daily-reboot.service` / `.timer` - ~daily
  monotonic preventive reboot, see "Daily preventive reboot" above.
- `deploy/systemd/water-meter-correction-listener.service` - persistent
  service, see "Human-in-the-loop notifications" above.
- `packages/water_meter.yaml` - HA-side staleness sensor + alert automation,
  plus the Approve/Reject/Modify notification-action automations and the
  `input_number`/`rest_command` they use.
- `tests/test_water_meter_*.py` - unit tests for the pure logic (sanity gate,
  config parsing, ROI cropping) and the package YAML; hardware/network paths
  (camera, ssocr, MQTT broker) are exercised for real only on the Pi.

## Manual deployment runbook

### 1. Flash the OS

Use Raspberry Pi Imager, choose **Raspberry Pi OS Lite (64-bit)**, and in the
advanced settings pre-configure hostname, SSH, Wi-Fi, and locale/timezone.

### 2. First login and OS packages

```bash
ssh <user>@water-meter.local
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-opencv python3-pip git build-essential \
    libimlib2-dev v4l-utils mosquitto-clients
```

### 3. Build ssocr (not in the Raspberry Pi OS repos)

```bash
git clone https://github.com/auerswal/ssocr.git
cd ssocr && make && sudo make install
ssocr --version
```

### 4. Deploy this repo to the Pi

```bash
sudo git clone <this-repo-url> /opt/hass-config
cd /opt/hass-config
python3 -m venv --system-site-packages venv   # reuse apt's python3-opencv
source venv/bin/activate
pip install paho-mqtt
```

(No PyYAML needed - calibration is stored as JSON, keeping `water_meter/config.py`
dependency-free like the rest of this package's pure-logic modules.)

### 5. Identify the webcam's stable device path

```bash
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
```

Use the `/dev/v4l/by-id/usb-...-video-index0` symlink, not `/dev/videoN`
(which can renumber across reboots/USB re-enumeration).

### 6. MQTT credentials

Create `/etc/water-meter/credentials.env` (not committed to git):

```bash
sudo mkdir -p /etc/water-meter
sudo tee /etc/water-meter/credentials.env >/dev/null <<'EOF'
WATER_METER_MQTT_USERNAME=z2muser
WATER_METER_MQTT_PASSWORD=<the real broker password>
EOF
sudo chmod 600 /etc/water-meter/credentials.env
```

Confirm connectivity and capture the light's exact `friendly_name`:

```bash
mosquitto_sub -h <broker-host> -p 1883 -u z2muser -P <password> -t 'zigbee2mqtt/#' -v
```

Toggle the chosen light from HA while this is running and watch for its
`.../set` and `.../availability` messages.

### 7. Mount the hardware

Webcam + light in one jig, fixed relative to the meter window, light offset
~30-45 degrees off the camera axis. Do not move it after calibration without
recalibrating.

### 8. Calibrate

```bash
# On the Pi, with the light forced on:
python3 -m water_meter.calibrate capture-only -o /tmp/reference_frame.jpg

# On a workstation with a display:
scp <user>@water-meter.local:/tmp/reference_frame.jpg .
python3 -m water_meter.calibrate calibrate --image reference_frame.jpg \
    --write-config calibration.json --test
scp calibration.json <user>@water-meter.local:/opt/water-meter/calibration.json
```

`calibrate` uses OpenCV's built-in `cv2.selectROI` - drag a box, Enter/Space
to confirm, Esc to move on. First the overall digit-strip ROI, then one box
per digit. While looking at the reference frame, also confirm whether every
digit is a clean static segment display or whether the lowest digit is a
rotating/sweep indicator (common on encoder registers) - if so, add its index
to `excluded_digit_indexes` in `calibration.json` so it's rounded down instead
of fought with OCR.

`--test` alone only exercises `ssocr`, since it runs on a workstation with
none of the Pi's deployment env vars - on a meter that actually needs the
fallback tiers (like this documented one, under a fixed glare streak), any
ssocr hiccup during `--test` fails immediately instead of proving out the
pipeline that will really be deployed. Pass `--templates-dir` (a local copy
of the Pi's `digit_templates/`) and/or `--vlm-host`/`--vlm-model`/
`--vlm-timeout` to exercise the same fallback chain `reader.py` uses:

```bash
python3 -m water_meter.calibrate calibrate --image reference_frame.jpg \
    --write-config calibration.json --test \
    --templates-dir ./digit_templates --vlm-host truenas.local:30068
```

### 9. Test, then install the timer

```bash
python3 -m water_meter.reader --dry-run
sudo cp deploy/systemd/water-meter-reader.service deploy/systemd/water-meter-reader.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now water-meter-reader.timer
journalctl -u water-meter-reader.service -f
```

### 10. Shadow mode, then cut over

Let it run against real hardware for a few days, comparing
`sensor.water_meter` (or the logged value in dry-run/journal output) against
manual meter reads and watching `images/rejects/` for false rejects, before
relying on it for HA statistics/automations. Manually stop the timer once to
confirm the `water_meter_reading_stale` automation fires as designed.
