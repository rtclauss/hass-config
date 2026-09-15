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
- Raspberry Pi 3B/3B+, running **Raspberry Pi OS Lite (64-bit)**, Debian 13
  "Trixie" - headless, no desktop needed.
- A USB webcam and an existing Zigbee bulb (already paired to zigbee2mqtt),
  mounted in a fixed jig in front of the meter's display window. Offset the
  light ~30-45 degrees from the camera axis (not coaxial) to avoid glare.

## Architecture

```text
systemd timer (every ~10 min; a run can take up to ~18 min in the worst case
                below, in which case the *next* tick is a safe no-op - see
                "Vision-LLM fallback")
  -> water_meter.reader (on the Pi)
       -> publish light ON straight to the zigbee2mqtt broker
       -> capture a frame (webcam), publish light OFF
       -> crop to the calibrated ROI / digit boxes
       -> OCR: ssocr (primary, fast) -> vision LLM (qwen3-vl via Ollama,
          optional, slow but reads through glare) -> OpenCV template match
          (last resort, fully offline)
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
  Ollama `/api/generate` endpoint with a tight, single-purpose prompt
  ("What N-digit number is shown on this water meter LCD? Answer with just
  the digits, nothing else.") and `stream: false`. It deliberately does
  **not** cap `num_predict` - an earlier attempt at bounding the model's
  "thinking" trace with a small token budget risked truncating the answer
  before it was actually emitted. A generous request timeout is the safer
  knob; see below.

**Latency is real and highly variable**, not just slow, on a CPU-only Ollama
host: one measured call took 123.9s total, of which only 48.4s was actual
token generation - Ollama's own timing fields (`eval_duration`,
`prompt_eval_duration`, `load_duration`) don't account for the rest, which
looks like host-level contention rather than anything about the model
itself. `DEFAULT_VLM_TIMEOUT` (480s) and the systemd unit's
`WATER_METER_VLM_TIMEOUT_SECONDS` were both raised after a live run hit a
shorter (240s) timeout, then the same generation was observed (via
`/api/ps`) to keep running server-side and complete anyway - a timeout that
short was silently throwing away calls that would have succeeded.

**Automatic requery on a suspicious value** (`water_meter/reader.py`,
`_requery_vlm_on_suspect_value`): the sanity gate's "value decreased" and
"implausible jump" rejections mean the digits parsed cleanly but the
resulting value looks wrong - the signature of a single misread digit
(confirmed live: even the VLM occasionally flips the glare-affected leading
digit), not a garbled read. Since the meter hasn't moved between the first
attempt and now, one extra VLM call against the *same* crop - with the
suspect value and the last confirmed reading given as context - gets a
second, better-informed answer instead of discarding the whole capture.
This fires at most once per run and only for those two rejection reasons;
a bad digit count, a non-numeric read, or an outright capture/OCR failure
means there's nothing a requery of the same image would fix.

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
Environment=WATER_METER_VLM_MODEL=qwen3-vl:4b
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
that reaches a human, but a bad VLM read can still be safely *rejected*
outright (never observed being *accepted*, thanks to the same non-decreasing/
max-delta checks that protect every other OCR path here).

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

## Known hardware issue: webcam USB lockups

Bench-tested on a **Raspberry Pi 3 Model B Plus**: the webcam has been
observed to wedge after a handful of captures (every subsequent
`cv2.VideoCapture` read times out with `V4L2: select() timeout`, even from a
freshly opened capture in a brand-new process) in a way that only a host
reboot clears - `water_meter/watchdog.py` (see above) auto-recovers this,
but the root cause is almost certainly **USB power contention specific to
this board**: the Pi 3B+ routes its onboard Ethernet through the same
internal USB hub as the external USB ports, and this webcam (Logitech C270,
bus-powered, up to 500mA) sits behind that same hub chain, competing with
network traffic for a shared, limited 5V rail.

**Recommended fix** (not yet applied): move the webcam to a **powered USB
hub** rather than the Pi's own ports. If that's not available, try disabling
USB autosuspend on the hub chain above the camera
(`echo on | sudo tee /sys/bus/usb/devices/<hub>/power/control`), and confirm
the Pi's own power supply is a genuine 2.5A+ rated unit.

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
- `deploy/systemd/water-meter-reader.service` / `.timer` - the oneshot
  service + timer, mirroring `deploy/systemd/inky-owner-suite.service`.
- `packages/water_meter.yaml` - HA-side staleness sensor + alert automation.
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
