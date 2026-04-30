# Inky E-Ink Displays

Issue: [#313](https://github.com/rtclauss/hass-config/issues/313)

This document is the source of truth for the first e-ink display rollout. Keep
hardware assignments, MQTT topics, payload contracts, display modes, and privacy
expectations here before wiring Home Assistant automations or Raspberry Pi
services.

## Hardware Assignments

| Display ID | Panel | Color semantics | Location | Driver |
| --- | --- | --- | --- | --- |
| `owner_suite` | Pimoroni Inky wHAT PIM408, red/black/white, 400x300 | Red means urgency or exception | Owner suite, exact placement TBD | Raspberry Pi Zero W |
| `office` | Yellow/black/white Inky display, 400x300, not yet confirmed | Yellow means emphasis or hospitality | Office, exact placement TBD | Raspberry Pi TBD |

Available Raspberry Pi hardware from issue #313:

- Raspberry Pi Zero W, assigned to `owner_suite`
- Raspberry Pi Zero
- Raspberry Pi 1
- Raspberry Pi 3 Model B
- Raspberry Pi 3 Model B+

Start the rollout with `owner_suite` because the red/black/white panel already
exists. Do not block renderer work on final mounting decisions, but document the
final placement and assigned Pi here before deploying the physical service.

## Architecture

Home Assistant owns display state. The Raspberry Pi owns rendering, caching, and
physical panel refresh.

```text
Home Assistant package/script
  -> MQTT retained-ish compact payload
  -> Raspberry Pi systemd service
  -> payload validation
  -> local render
  -> duplicate content hash check
  -> Inky refresh
  -> last-good payload/image cache
```

The Pi service must keep the last valid image visible when Home Assistant or
MQTT is unavailable. Failed renders must not blank the display.

## MQTT Topics

Use one command topic per display:

| Display ID | Topic |
| --- | --- |
| `owner_suite` | `home/inky/owner_suite/state` |
| `office` | `home/inky/office/state` |

Future health/status topics should be separate from the desired-state topic:

| Display ID | Topic |
| --- | --- |
| `owner_suite` | `home/inky/owner_suite/status` |
| `office` | `home/inky/office/status` |

The initial publisher should avoid clock-tick redraws. Publish only when a
meaningful source value changes, then let the Pi suppress duplicate payloads by
content hash.

## Payload Contract

Payloads are compact JSON. Required fields:

```json
{
  "schema_version": 1,
  "display_id": "owner_suite",
  "mode": "night_preview",
  "accent": "red",
  "title": "Alarm 6:30",
  "subtitle": "Workday tomorrow",
  "sections": [
    {
      "type": "rows",
      "rows": [
        {"icon": "mdi:weather-snowy", "label": "Weather", "value": "24F Snow", "level": "normal"},
        {"icon": "mdi:door-closed", "label": "Doors", "value": "Closed", "level": "normal"}
      ]
    }
  ],
  "footer": "Updated 21:42"
}
```

Supported `accent` values:

- `red`
- `yellow`
- `black`

Supported row `level` values:

- `normal`
- `emphasis`
- `urgent`

Rows may include an optional `icon` field. Use Material Design Icons names with
the `mdi:` prefix so payloads stay aligned with Home Assistant icon names. The
Pi renderer should support a small weather-first fallback icon set and skip
unknown icons instead of failing the render.

Initial weather icon names:

- `mdi:weather-sunny`
- `mdi:weather-partly-cloudy`
- `mdi:weather-cloudy`
- `mdi:weather-rainy`
- `mdi:weather-snowy`
- `mdi:weather-lightning`

The renderer must tolerate missing optional fields and unknown section types.
Unknown content should be skipped, not rendered as an error screen.

## Layout Rules

- Canvas is `400x300`.
- Use high-contrast white, black, and one accent color.
- Text must be readable from roughly 4 feet away.
- Prefer one large title, one subtitle, and at most four status rows.
- Reject dense paragraphs, tiny legends, and dashboard-like tables.
- Red on `owner_suite` means urgent or exceptional.
- Yellow on `office` means emphasis or hospitality, not urgency.
- Do not render rapidly changing clocks.

## Owner-Suite Modes

`owner_suite` is private and owner-focused. It may show personal wake, trip,
weather, and house-status context.

| Mode | Purpose | Candidate fields |
| --- | --- | --- |
| `night_preview` | Bedtime preview before sleep | next alarm, tomorrow workday/meeting state, overnight weather, door/garage exceptions |
| `morning` | Wake sequence is active | wake status, weather, first meeting/departure note, urgent house exceptions |
| `up_for_day` | Morning activity confirms the day has started | weather, house mode, garage/door/weather exceptions |
| `midday` | Low-frequency daytime refresh | current weather, trip mode, severe weather, garage/door status |

Known source-of-truth areas:

- Wake-up alarm sync and helper state: `packages/ios_wakeup.yaml`
- Owner-suite wake transitions: `packages/workday.yaml`
- Weather helper sensors: `packages/weather.yaml`
- Wake-up behavior specification: `specs/alarm_wakeup.allium`
- Room privacy policy: `docs/room_intent.yaml`

## Home Assistant Payload Builder

Owner-suite publishing lives in `packages/inky_displays.yaml`.

Primary entities:

- `script.publish_owner_suite_inky_display`: builds and publishes the compact
  owner-suite payload to `home/inky/owner_suite/state`.
- `automation.publish_owner_suite_inky_display`: coalesces meaningful source
  changes with a 15-second restart delay, then calls the publish script.

The automation listens to wake alarm helpers, wake-up firing state, house mode,
guest mode, Ryan's home state, bed/owner-suite activity, trip/vacation state,
garage/front-door exceptions, weather alerts, active weather, and a noon
refresh. It does not listen to `sensor.time`, so it will not redraw on clock
ticks.

The automation publishes only when guest mode is active, or when Ryan is home
and trip mode is off. While Ryan is away or trip mode is on with guest mode off,
the display keeps its last image and skips refreshes. Turning guest mode on or
Ryan returning home is itself a meaningful source change and publishes again
after the normal 15-second coalescing delay.

Current owner-suite modes:

| Mode | Selected when | Title | Subtitle |
| --- | --- | --- | --- |
| `night_preview` | Explicit mode or house mode is `night`, `in_bed`, or `asleep` | `Tonight` | `Next alarm and overnight status` |
| `morning` | Explicit mode or `input_boolean.wakeup_alarm_firing` is on | `Good Morning` | `Wake sequence active` |
| `up_for_day` | Explicit mode or automatic pre-noon non-sleep state | `Up For Day` | `Morning activity confirmed` |
| `midday` | Explicit mode, noon trigger, or automatic afternoon state | `Midday` | `Low-frequency refresh` |

Current owner-suite rows:

| Row | Value source | Level behavior |
| --- | --- | --- |
| Weather | `sensor.outside_temperature` plus `sensor.active_weather_entity_id` weather state | `urgent` when NWS alerts are active |
| Alarm | `input_datetime.weekday_alarm` or `input_datetime.weekend_alarm` when the matching alarm helper is on | `emphasis` in `night_preview` when alarm is enabled |
| Meeting | `input_datetime.next_work_meeting` when `input_boolean.special_meeting` is on | `emphasis` when special meeting is on |
| Status | First active status from weather alert, garage door, front door, trip mode, vacation, otherwise `All clear` | `urgent` for alert/door/garage, `emphasis` for trip/vacation |

The footer uses 24-hour local time, for example `Updated 21:42`. This timestamp
is generated only when the payload is published. Do not add `sensor.time` or a
minute-level clock trigger for this field.

Manual publish from Home Assistant Developer Tools:

```yaml
action: script.publish_owner_suite_inky_display
data:
  mode: night_preview
```

## Office Modes

The office is guest-capable. When guest mode is active, office display content
must be safe for a guest to read.

| Mode | Purpose |
| --- | --- |
| `focus` | Owner work focus status when no guest context is active |
| `home_arrival` | Arrival-oriented owner information when no guest context is active |
| `midday` | Low-frequency daytime owner refresh when no guest context is active |
| `guest_info` | Guest-safe hospitality screen |

`guest_info` should include only house-safe content:

- guest Wi-Fi QR code
- guest SSID text
- 3-day weather strip
- indoor temperature
- Ecobee preset
- house-safe status rows
- footer prompt such as `Scan for Guest Wi-Fi`

Guest mode must suppress personal, work, meeting, calendar, and owner-location
details on the office display.

## Local Renderer Testing

Always keep this section current when adding, renaming, or removing renderer
samples.

Run the focused renderer tests:

```bash
python3 -m pytest tests/test_inky_display_renderer.py
```

Render one sample locally:

```bash
python3 -m inky_display.cli \
  inky_display/samples/owner_suite_night_preview.json \
  /tmp/owner_suite_night_preview.png
```

Render all current owner-suite samples:

```bash
python3 -m inky_display.cli \
  inky_display/samples/owner_suite_night_preview.json \
  /tmp/owner_suite_night_preview.png

python3 -m inky_display.cli \
  inky_display/samples/owner_suite_morning.json \
  /tmp/owner_suite_morning.png

python3 -m inky_display.cli \
  inky_display/samples/owner_suite_up_for_day.json \
  /tmp/owner_suite_up_for_day.png

python3 -m inky_display.cli \
  inky_display/samples/owner_suite_midday.json \
  /tmp/owner_suite_midday.png
```

Expected result for each rendered sample:

- PNG output is `400x300`.
- Weather rows show the configured fallback icon when the sample includes an
  `mdi:weather-*` icon.
- Unknown icons are skipped instead of failing the render.
- Text stays high-contrast against emphasis or urgent row backgrounds.
- Optional JSON `null` values render as blank text.

Run the Pi service cache/dedup tests:

```bash
python3 -m pytest tests/test_inky_display_service.py
```

Run the MQTT-backed Pi service locally after installing `paho-mqtt` on the Pi:

```bash
python3 -m pip install paho-mqtt
python3 -m inky_display.service --check-config

INKY_DISPLAY_ID=owner_suite \
INKY_MQTT_HOST=homeassistant.local \
INKY_MQTT_PORT=1883 \
INKY_MQTT_TOPIC=home/inky/owner_suite/state \
INKY_CACHE_DIR=/var/lib/inky-display/owner_suite \
python3 -m inky_display.service
```

Run a real panel refresh on the Pi after the Inky wHAT is attached:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo apt-get update
sudo apt-get install -y libopenblas0-pthread
python3 -m pip install paho-mqtt Pillow inky
sudo reboot
```

After the reboot, render the next MQTT payload to the physical red/black/white
Inky wHAT:

```bash
INKY_DISPLAY_ID=owner_suite \
INKY_MQTT_HOST=homeassistant.local \
INKY_MQTT_PORT=1883 \
INKY_MQTT_TOPIC=home/inky/owner_suite/state \
INKY_CACHE_DIR=/var/lib/inky-display/owner_suite \
INKY_HARDWARE_ENABLED=true \
INKY_PANEL_TYPE=auto \
INKY_PANEL_COLOR=red \
INKY_ROTATION=0 \
python3 -m inky_display.service
```

For a non-production physical smoke test, use a temporary topic such as
`home/inky/owner_suite/real_test`, start the service with that topic, and publish
one sample payload to it. Expected result: the panel refreshes once, the cache
contains a `400x300` `last_image.png`, and the service log has no traceback,
deprecation warning, or `Failed to update Inky panel` message.

Keep `INKY_PANEL_TYPE=auto` for boards with a valid Inky EEPROM. The owner-suite
red Inky wHAT currently reports as `Red wHAT (SSD1683)`, which needs the
auto-detected driver rather than the legacy `what` driver. For older boards that
cannot be detected automatically, set `INKY_PANEL_TYPE=what` and
`INKY_PANEL_COLOR=red`.

The service writes:

- `last_payload.json`
- `last_image.png`
- `last_hash.txt`

Duplicate payload hashes are ignored and do not refresh the physical panel.
Invalid payloads are logged and do not overwrite the last good cache.

## Raspberry Pi Service

The first Pi target is the owner-suite Pi Zero W. Use
`deploy/systemd/inky-owner-suite.service` as the starting systemd unit and
adjust `WorkingDirectory`, `INKY_MQTT_HOST`, and optional MQTT credentials for
the deployed Pi.

## Rollout Order

1. Build local renderer and sample payloads for `owner_suite`.
2. Add HA-side MQTT payload builder for `owner_suite`.
3. Deploy one Pi service with cache restore and duplicate suppression.
4. Verify alarm sync, wake firing, morning activity, noon refresh, and exception
   rendering on the physical panel.
5. Confirm and add the office panel hardware.
6. Add `office` private modes and `guest_info`.
