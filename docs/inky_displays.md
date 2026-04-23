# Inky E-Ink Displays

Issue: [#313](https://github.com/rtclauss/hass-config/issues/313)

This document is the source of truth for the first e-ink display rollout. Keep
hardware assignments, MQTT topics, payload contracts, display modes, and privacy
expectations here before wiring Home Assistant automations or Raspberry Pi
services.

## Hardware Assignments

| Display ID | Panel | Color semantics | Location | Driver |
| --- | --- | --- | --- | --- |
| `owner_suite` | Pimoroni Inky wHAT PIM408, red/black/white, 400x300 | Red means urgency or exception | Owner suite, exact placement TBD | Raspberry Pi TBD |
| `office` | Yellow/black/white Inky display, 400x300, not yet confirmed | Yellow means emphasis or hospitality | Office, exact placement TBD | Raspberry Pi TBD |

Available Raspberry Pi hardware from issue #313:

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
        {"label": "Weather", "value": "24F Snow", "level": "normal"},
        {"label": "Doors", "value": "Closed", "level": "normal"}
      ]
    }
  ],
  "footer": "Updated 9:42 PM"
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

## Rollout Order

1. Build local renderer and sample payloads for `owner_suite`.
2. Add HA-side MQTT payload builder for `owner_suite`.
3. Deploy one Pi service with cache restore and duplicate suppression.
4. Verify alarm sync, wake firing, morning activity, noon refresh, and exception
   rendering on the physical panel.
5. Confirm and add the office panel hardware.
6. Add `office` private modes and `guest_info`.

