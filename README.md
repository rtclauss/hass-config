# The Brewery Home Assistant Configuration 🍺
[![Build Status](https://api.travis-ci.com/rtclauss/hass-config.svg?branch=main)](https://app.travis-ci.com/github/rtclauss/hass-config)

[Home Assistant](https://home-assistant.io/) configuration files (YAMLs) and [AppDaemon](https://appdaemon.readthedocs.io/en/latest/) apps.

## CI + Local Validation Baseline

- This repo pins local tooling Python in `.python-version`.
- CI validates that this pinned version is still compatible with the latest official `homeassistant` release from [PyPI](https://pypi.org/project/homeassistant/).
- Config checks run against `ghcr.io/home-assistant/home-assistant:stable` so validation tracks current Home Assistant stable releases.
- As of 2026-03-15, latest `homeassistant` requires Python `>=3.14.2`, so `.python-version` is set to `3.14.3`.

## Branch Flow

- `main` is stable/live.
- `develop` is the integration branch used for Home Assistant soak testing.
- Start feature work in a worktree from `origin/develop`.
- Open feature/fix PRs to `develop`, explicitly setting the base branch.
- `main` only accepts promotion PRs from `develop`.
- After HA validation, open a promotion PR from `develop` to `main`.

### Local Setup

```bash
# Use the pinned interpreter from .python-version (for example via pyenv)
python -m pip install --upgrade pip yamllint
python scripts/check_ha_python_support.py --python-version-file .python-version
uv run --with pytest pytest
```

## Music Assistant Media Flow

Music playback automations now target the Music Assistant-backed Sonos entities, which are the `_2` media players:

- `media_player.bedroom_sonos_2`
- `media_player.bathroom_sonos_2`
- `media_player.office_sonos_2`
- `media_player.den_sonos_2`
- `media_player.tiki_room_2`

The reusable media helpers live in `packages/media_player.yaml`:

- `script.music_assistant_play_item`: thin wrapper around `music_assistant.play_media` for any Music Assistant URI, URL, or plain item name. Pass `media_type` explicitly when you need to disambiguate a track, album, artist, playlist, or radio item.
- `script.music_assistant_search_music`: searches Music Assistant from the dashboard controls and populates the result picker.
- `script.music_assistant_play_selected_search_result`: plays or queues the selected Music Assistant search result.
- `script.music_assistant_prepare_bedroom_group`: regroup bedroom/bathroom and optionally office/den depending on guest mode.
- `script.music_assistant_prepare_arrival_group`: regroup the arrival playback zone.
- `script.music_assistant_prepare_house_party_group`: regroup all Sonos players for party modes.
- `script.music_assistant_play_spotify_uri`: accepts a Spotify URI or `open.spotify.com` URL and converts it into the Music Assistant provider URI used by `music_assistant.play_media`.
- `script.music_assistant_radio_wake_up`: shared wake-up flow for radio stations.

The Siri/Homebridge entrypoint for the Tiki Time party mode is `script.tiki_time` in `packages/tiki_time.yaml`.

### Adding Another Playlist

If an existing script already picks from a list, the normal change is just to append one more URI or plain Music Assistant item name to that script's `plists` array in `packages/media_player.yaml`.

Examples:

- `script.bedroom_playlist_0` through `script.bedroom_playlist_5` for cube-triggered bedroom playlists
- `script.spotify_arrival` for arrival music
- `script.spotify_bedtime` for bedtime music
- `script.spotify_wake_up` for morning music

Accepted playlist values:

- `spotify:playlist:...`
- `spotify:album:...`
- `spotify:artist:...`
- `https://open.spotify.com/playlist/...`
- `https://open.spotify.com/album/...`
- `https://open.spotify.com/artist/...`
- `https://open.spotify.com/track/...`
- Music Assistant URIs or plain item names, for mixed lists that call `script.music_assistant_play_item`

If you are creating a brand new script, prefer calling the helper instead of using `media_player.play_media` directly:

```yaml
- action: script.music_assistant_play_spotify_uri
  data:
    entity_id: media_player.bedroom_sonos_2
    spotify_uri: "spotify:playlist:37i9dQZF1DX4WYpdgoIcn6"
```

Notes:

- The generic helper now passes Music Assistant URIs and plain item names through directly. Use `media_type` when a name is ambiguous.
- `script.music_assistant_play_spotify_uri` remains as a compatibility wrapper for Spotify URLs and URIs.

### Searching and Queuing Music Assistant Items

The `Music Assistant` section on the dashboard includes a small search flow:

1. Enter a plain-text query in `input_text.music_assistant_search_query`.
2. Optionally pick a provider token from `input_select.music_assistant_provider_filter`.
3. Choose the media type from `input_select.music_assistant_search_media_type`.
4. Press `script.music_assistant_search_music` to populate `input_select.music_assistant_search_results`.
5. Optionally choose a target playlist script from `input_select.music_assistant_playlist_target`.
6. Use `script.music_assistant_play_selected_search_result` to play the selected result now or add it to the current queue.
7. Use `script.music_assistant_add_selected_search_result_to_playlist` to append the selected Music Assistant URI to the chosen `plists`-based script and reload scripts.

The search helper derives the Music Assistant `config_entry_id` dynamically from `media_player.bedroom_sonos_2`, so it does not depend on a hard-coded config entry. The provider dropdown refreshes from the current unfiltered search response, which keeps the options aligned with the providers that can satisfy the active query.

The supported playlist-script targets are `spotify_bedtime`, `spotify_wake_up`, `spotify_arrival`, and `bedroom_playlist_0` through `bedroom_playlist_5`. Appending a result updates `packages/media_player.yaml` in place and then reloads Home Assistant scripts so the change is immediately available.

### Adding Another Radio Station

Radio wake-up scripts now use Music Assistant item URIs instead of Sonos favorites or Spotify Connect source selection.

Current examples:

- `library://radio/12`
- `tunein--S3NwgspV://radio/s34350`
- `tunein--S3NwgspV://radio/s20620`

Recommended workflow:

1. Find the station in Music Assistant first.
2. Copy the Music Assistant radio item URI.
3. Pass that URI to `script.music_assistant_radio_wake_up`.

Example wrapper script:

```yaml
my_new_radio_wake_up:
  alias: My New Radio Wake Up
  sequence:
    - action: script.music_assistant_radio_wake_up
      data:
        radio_uri: "tunein--S3NwgspV://radio/s12345"
        initial_delay: 5
```

If you need to discover a station URI from Home Assistant, use Music Assistant search/library tools or the `music_assistant.search` / `music_assistant.get_library` services in Developer Tools and copy the returned item id.

### Validation

After changing media scripts, validate the config the same way CI does:

```bash
yamllint -d "{extends: relaxed, rules: {line-length: disable, empty-lines: disable, truthy: disable}}" \
  configuration.yaml automations.yaml blueprints packages zigbee2mqtt

# If Docker is available
docker run --rm -v "$PWD:/config" ghcr.io/home-assistant/home-assistant:stable \
  python -m homeassistant --config /config --script check_config
```

## Feature Docs

- [House Transition Framework](docs/house_transition_framework.md)
- [Room Intent Policy](docs/room_intent.yaml)
- [Room Naming Model](docs/room_names.md)
- [ESPHome Layout And Bermuda BLE Proxy Notes](docs/esphome.md)
- [EV Charging Tariff](docs/ev_charging_tariff.md)
- [Tesla Departure Planner](docs/tesla_departure_planner.md)

I have Home Assistant running on an [Intel NUC]().  This has been a work in progress since Nov 2015 (HA v0.7 or earlier).

I use the new dashboards in 0.107 to create a [dashboard for guests](https://github.com/rtclauss/hass-config/blob/main/ui-guest.yaml) on an Amazon Fire Tab running Fully Kiosk Browser.

Software on the NUC:
* [Home Assistant](https://home-assistant.io/) via [Hass.io](https://www.home-assistant.io/hassio/)
* Running in Hass.io
  * [AppDaemon](https://github.com/hassio-addons/addon-appdaemon)
  * [VSCode](https://github.com/hassio-addons/addon-vscode)
  * [Mosquitto Broker](https://home-assistant.io/addons/mosquitto/)
  * [Music Assistant](https://music-assistant.io/) - Main playback engine for Sonos/Spotify/radio automations
  * ~~[Traccar](https://github.com/hassio-addons/addon-traccar) - Used with OBDII Sensor to track my car.~~ New car has built-in tracking
  * [JupyterLab Lite](https://github.com/hassio-addons/addon-jupyterlab-lite) Only sometimes when I need to figure out event correllation
  * [ESPHome](https://esphomelib.com/esphomeyaml/index.html) - Used for [Water Softener](https://github.com/rtclauss/hass-config/blob/main/packages/water_softener.yaml), [Bed Occupancy Sensor](https://github.com/rtclauss/hass-config/blob/main/esphome/bedloadcell1.yaml), and [BLE Proxy](https://github.com/rtclauss/hass-config/blob/main/esphome/bluetoothproxy1.yaml)
  * ~~[Zwave-JS](https://www.home-assistant.io/integrations/zwave_js)~~ Moving to Zigbee/Thread/Matter
  * [I Can't Believe It's Not Valetudo](https://github.com/Poeschl/Hassio-Addons/tree/master/ICantBelieveItsNotValetudo)
  * [Home Assistant Google Drive Backup](https://github.com/sabeechen/hassio-google-drive-backup)
  * [Matter Server](https://github.com/home-assistant/addons/tree/master/matter_server)
* Running elsewhere
  * [rtlamr](https://github.com/bemasher/rtlamr) - Runs on a Pi4 and collects ~~electrical~~ gas utility info.
  * [Zigbee2MQTT](https://zigbee2mqtt.io/) - Zigbee control over MQTT

## Device Audit (2026-03-29)

This section replaces the older static hardware list with a split between
hardware that has been retired from service and device families that are
verifiably live in the current Home Assistant instance. When an older device was
replaced rather than simply removed, the retired row links to the live
replacement below.

Follow-up for item-level and model-level inventory work: [Issue #247](https://github.com/rtclauss/hass-config/issues/247).

## Retired Devices

| README entry | Outcome | Replacement | Notes |
| --- | --- | --- | --- |
| Nest Thermostat | Replaced | [Ecobee](#live-ecobee) | No live Nest integration remains. |
| Amazon Echo | Removed | None | Echo hardware has been retired from the house. |
| Amazon Echo Dot Gen 2 | Removed | None | Echo Dot hardware has been retired from the house. |
| Amazon Fire TV | Removed | None | No live Fire TV device or integration remains. |
| HUSBZB-1 Zigbee / Z-Wave stick | Replaced | [Zigbee / Thread / Matter infrastructure](#live-zigbee-infra) | The old HubZ `zha` and `zwave_js` entries are ignored or not loaded. |
| GoControl Z-Wave Thermostat | Replaced | [Ecobee](#live-ecobee) | The thermostat role moved to Ecobee Premium and room sensors. |
| Leviton Vizia RF+ VRS05-1LZ | Replaced | [Inovelli](#live-inovelli) | The old Z-Wave wall-switch footprint is now on Zigbee lighting controls. |
| Leviton Vizia coordinating remote switch | Replaced | [Inovelli](#live-inovelli) and [IKEA](#live-ikea) | Current room-control hardware is now anchored on Zigbee switches and remotes. |
| GE Z-Wave outdoor module | Removed | None | No direct verified successor is visible in the current registry. |
| GE Z-Wave appliance switch | Removed | None | No direct verified successor is visible in the current registry. |
| Bed presence sensor using Ecolink + pressure mat | Replaced | [ESPHome / ratgdo](#live-esphome-ratgdo) | Bed occupancy is now handled by live ESPHome bed load-cell hardware. |
| Bed Occupancy Sensor using copper foil / foam | Replaced | [ESPHome / ratgdo](#live-esphome-ratgdo) | The original DIY bed sensor was replaced by the newer ESPHome bed-presence stack. |
| GoControl Z-Wave plug-in dimmer | Removed | None | It does not appear in the current live registry. |
| Zooz ZEN26 | Replaced | [Inovelli](#live-inovelli) | The old Z-Wave switch path is no longer present. |
| Inovelli ZSW31-SN Z-Wave dimmers | Replaced | [Inovelli](#live-inovelli) | The live system now uses Inovelli Zigbee 2-in-1 switches and dimmers. |
| Electro Llama ZZH Stick | Replaced | [Zigbee / Thread / Matter infrastructure](#live-zigbee-infra) | Zigbee2MQTT now runs on a Nabu Casa `ZBT-2`. |
| Enbrighten 43100 Outdoor Switch | Removed | None | No current live-registry match could be confirmed. |
| Lutron Pico LZL-4B-WH-L01 reset remote | Removed | None | No current live-registry match could be confirmed. |
| SmartThings Motion Sensor | Replaced | [Aqara](#live-aqara) | Current motion sensing is clearly covered by Aqara devices; this specific sensor is not live. |
| Hampton Bay / King of Fans Zigbee fan controller | Replaced | [Bond](#live-bond) | Fan control is now handled by the live Bond bridge. |
| MyQ Garage Door | Replaced | [ESPHome / ratgdo](#live-esphome-ratgdo) | The garage door is now a live `ratgdo` ESPHome device. |
| Generic OBDII GPRS Real Time Tracker | Replaced | [Tesla](#live-tesla) | Tesla connectivity now covers the vehicle-tracking use case. |

## Live Devices

| Device family | Current live examples |
| --- | --- |
| <a id="live-apple"></a>Apple / HomePod / Apple TV | Apple TV 4K plus multiple HomePod Minis via `apple_tv`. |
| <a id="live-ecobee"></a>Ecobee | Ecobee Premium thermostat plus remote room sensors in the bedroom, office, den, basement, and guest room. |
| <a id="live-sonos"></a>Sonos | Sonos One, Move, Port, and SYMFONISK picture-frame devices across both `sonos` and `music_assistant`. |
| <a id="live-aqara"></a>Aqara | Motion, temperature/humidity, leak, contact, vibration, button, and cube devices on Zigbee2MQTT, plus an Aqara Motion and Light Sensor P2 on Matter. |
| <a id="live-ikea"></a>IKEA | FYRTUR blinds, PARASOLL contact sensors, TRADFRI outlets and remotes, SOMRIG shortcut buttons, SYMFONISK sound remotes, and a RODRET dimmer. |
| <a id="live-inovelli"></a>Inovelli | Multiple Zigbee 2-in-1 switches and dimmers used for room lighting and smart-bulb mode control. |
| <a id="live-philips-hue"></a>Philips Hue | Hue downlights, filament bulbs, outdoor fixtures, and other bulbs on Zigbee2MQTT. |
| <a id="live-eaton-halo"></a>Eaton / Halo | Halo Zigbee downlights in hallway and bathroom areas. |
| <a id="live-sengled"></a>Sengled | Energy-monitoring smart plugs used for the CPAP and sump pump. |
| <a id="live-peanut"></a>Securifi / Peanut Smart Plug | A live Peanut Smart Plug remains paired and in service. |
| <a id="live-ecosmart"></a>EcoSmart | Tunable-white Zigbee bulbs still used in the owner suite lamps. |
| <a id="live-xiaomi"></a>Xiaomi | Dafang cameras and Xiaomi BLE `MiFlora` plant sensors remain active. |
| <a id="live-esphome-ratgdo"></a>ESPHome / ratgdo | Water softener sensor, bed load cells and bed presence, Bluetooth proxies, and the `ratgdo` garage-door controller. |
| <a id="live-zigbee-infra"></a>Zigbee / Thread / Matter infrastructure | Zigbee2MQTT on Nabu Casa `ZBT-2`, plus active `SkyConnect`, `Thread`, `OTBR`, and `Matter` integrations. |
| <a id="live-bond"></a>Bond | Bond Bridge fan control for den, office, guest room, and owner suite fans. |
| <a id="live-localtuya"></a>LocalTuya / Good Earth | Good Earth / Tuya LED flat panels in kitchen and laundry areas. |
| <a id="live-rachio"></a>Rachio | Rachio Gen 3 irrigation controller and zone switches. |
| <a id="live-smartthings"></a>SmartThings | The modified SmartThings Arrival Sensor is still paired via Zigbee2MQTT. |
| <a id="live-tesla"></a>Tesla | Tesla Model 3 (`Nigori`) on the custom Tesla integration. |
| <a id="live-unifi"></a>UniFi | The `unifi` integration is active for network entities, WLANs, and device trackers, although exact hardware model inventory is no longer fully represented in Home Assistant. |
| <a id="live-adaptive-lighting"></a>Adaptive Lighting | Active room-specific Adaptive Lighting instances across the lighting stack. |

Coordinator and protocol note:

- Zigbee has moved from the older HubZ/ZZH era to Zigbee2MQTT on `ZBT-2`.
- New device growth is now clearly moving toward `Thread` and `Matter`.
- Alexa exposure may still exist for selected entities, but the Echo hardware
  itself has been retired.

**AppDaemon Apps:**
* Sync workflow: [`docs/appdaemon_sync.md`](docs/appdaemon_sync.md) keeps the tracked `appdaemon/` tree aligned with the live Supervisor add-on under `addon_configs`.
* [Bayesian Device Tracker](appdaemon/apps/tracker.py) - Merges GPS location info with bayesian binary sensor to give ground-truth location tracking.  Uses bayesian data to eliminate red-herrings when arriving at home.  Could be extended to other zones if you have multiple `device_tracker`s
* [Lighting Fade-In](appdaemon/apps/brighten_lights.py) - Fades in lights from `off` over a pre-defined interval on a work (non-weekend, non-holiday) day.
* [Music Fade-in](appdaemon/apps/fade_in_music.py) - Fades in music when I wake up in the morning
* [deConz button events](appdaemon/apps/deconz_helper.py) - Translates Xiaomi button events into a generic sensor.
* [Magic Cube](appdaemon/apps/magic_cube.py) - Translates Xiaomi Magic Cube events into actions controlling my living room Hue lights
* [Automatic event helper](appdaemon/apps/automatic_helper.py) - Similar to deCONZ helper this translates matic events into a generic sensor.
* ~~[Nest Travel helper](appdaemon/apps/nest_travel_helper.py) - When driving long distances the Nest will switch from heating/cooling back to away mode if you don't arrive home soon enough.  This listens for those changes and keeps Nest from switching back to away mode.~~
* ~~[Schedy](appdaemon/apps/schedy_heating.yaml) - Replacement for Nest. Work in Progress.~~
* [Thermostat Stats](https://github.com/rtclauss/hass-config/blob/main/appdaemon/apps/thermostat_stats.py) - Gathers historical house temperature data.  Will feed into ML model to predict time to temp, etc.

**Apple Shortcuts**
* [Set wakeup time](https://www.icloud.com/shortcuts/61be3701823f444dbae0de1626020025) - [Slowly turn on bedroom lights in the morning before a meeting](https://github.com/rtclauss/hass-config/blob/main/packages/workday.yaml#L107)
* iOS personal automation: run every day at `9:00 PM`, find the wake-up alarm you want to mirror on the phone, format its time as `HH:mm`, and `POST` JSON to `https://<your-home-assistant>/api/webhook/ios_phone_wakeup_alarm_sync` with `{"alarm_time":"07:30"}`. If there is no enabled alarm for the next day, send `{"alarm_enabled": false}` instead. If JSON is awkward, the webhook also accepts query parameters.

Shortcut recipe:

1. In `Shortcuts` create a `Personal Automation`.
2. Choose `Time of Day`, set it to `9:00 PM`, select `Daily`, and disable `Run After Confirmation`.
3. Add `Find Alarms` and filter to the alarm you want Home Assistant to mirror.
4. Recommended filter: `Label is Wake Up` and `Is Enabled is On`.
5. If you only keep one wake-up alarm on the phone, using the first enabled alarm is fine.
6. Add `If` and branch on whether `Find Alarms` has any value.
7. In the `If` branch, add `Get Item from List` and choose the `First Item`.
8. Add `Get Details of Alarm` and select `Time`.
9. Add `Format Date` and use custom format `HH:mm`.
10. Add `Dictionary` with one key: `alarm_time`.
11. Set the `alarm_time` value to the formatted date output from the previous step.
12. In the `Otherwise` branch, add `Dictionary` with one key: `alarm_enabled`.
13. Set the `alarm_enabled` value to `false`.
14. After the `If`, add `Get Contents of URL`.
15. Set the URL to `https://<your-home-assistant>/api/webhook/ios_phone_wakeup_alarm_sync`.
16. Set `Method` to `POST`.
17. Set `Request Body` to `JSON`.
18. Set the JSON payload to the dictionary output from the `If`.

Expected payload when an alarm exists:

```json
{
  "alarm_time": "07:30"
}
```

Expected payload when there is no alarm:

```json
{
  "alarm_enabled": false
}
```

Suggested Shortcut action flow:

```text
Find Alarms
If Find Alarms has any value
  Get Item from List (First Item)
  Get Details of Alarm (Time)
  Format Date (HH:mm)
  Dictionary
    alarm_time: Formatted Date
Otherwise
  Dictionary
    alarm_enabled: false
End If
Get Contents of URL
```
