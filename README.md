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

**Devices in Use:**
* Apple/iOS Devices including AppleTV and HomePod Mini
* ~~[Nest Thermostat]()~~ ~~Replaced with Z-wave Thermostat and [Schedy](https://github.com/rtclauss/hass-config/blob/main/appdaemon/apps/schedy_heating.yaml)~~
* [Ecobee Premium](https://www.ecobee.com/en-us/smart-thermostats/smart-thermostat-premium/) Love those remote sensors!
* [Amazon Echo](http://amzn.to/2i6mShX)
* [Amazon Echo Dot Gen 2](http://amzn.to/2hvCexj)
* Sonos One Speakers
* Xiaomi Dafang Cameras running [custom firmware](https://github.com/EliasKotlyar/Xiaomi-Dafang-Hacks)
* Xiaomi MiFlora
* ESP8266 with [VL53L0X](https://www.amazon.com/gp/product/B07F3RH7TC/ref=ppx_yo_dt_b_asin_title_o00_s00?ie=UTF8&psc=1) to measure salt level in [water softener](https://github.com/rtclauss/hass-config/blob/main/packages/water_softener.yaml). See [this commit](https://github.com/rtclauss/hass-config/commit/85b1eade336c0fc94031241b494203fb55b3a7d8) for more info.
* ~~HUSBZB-1 Zigbee/Z-Wave Stick (for Z-Wave and Zigbee~~)
  * ~~Z-Wave~~
    * ~~[GoControl Z-Wave Thermostat](https://www.amazon.com/GoControl-Thermostat-Z-Wave-Battery-Powered-Works/dp/B00ZIRV40K)~~
    * ~~[Leviton Switch Vizia RF+ VRS05-1LZ](https://www.amazon.com/gp/product/B001HT6NKO/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) - 3 wire 3-way switch.~~
    * ~~[Leviton Vizia + Digital Coordinating Remote Switch](https://www.amazon.com/gp/product/B001HT4M70/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1)~~
    * ~~GE Z-Wave Wireless Smart Lighting Control Outdoor Module~~
    * ~~GE Z-Wave Wireless Smart Lighting Control Appliance Switch~~
    * ~~Bed presense sensor (2x): [Ecolink Z-Wave door/window sensor](https://www.amazon.com/Ecolink-Intelligent-Technology-Operated-DWZWAVE2-ECO/dp/B00HPIYJWU) mated with [Ideal pressure mat](https://www.amazon.com/Ecolink-Intelligent-Technology-Operated-DWZWAVE2-ECO/dp/B00HPIYJWU)~~ Replaced by custom solution below
    * ~~[Bed Occupancy Sensor](https://community.home-assistant.io/t/bed-occupancy-sensor-using-parts-you-have/189490) Following N-I1's design but using a large, closed-cell foam sheet covered with copper foil on both sides.~~
    * [GoControl Z-Wave Plug-in Dimmer](https://www.amazon.com/GoControl-Z-Wave-Plug-Dimmer-Module/dp/B00E1OXK3A/)
    * ~~[Zooz Z-Wave Plus S2/ZEN26](https://www.amazon.com/gp/product/B07K1T8Z74/ref=ppx_yo_dt_b_asin_title_o00_s00?ie=UTF8&psc=1)~~
    * ~~[Inovelli ZSW31-SN Dimmer Switches](https://support.inovelli.com/portal/en/kb/articles/products-switches-dimmer-lzw31-sn-spec-sheet): These are great multifunctional dimmers which have disableable relays so you can control smart bulbs which are plugged in to the controlled socket. To disable the relay, click the Control button 8 times.  Then you use Z-Wave events to control the lights as you see fit.  I use this in my guest room to control the ceiling fan light (ceiling fan is controllable by chain) which is on the circuit and to control the two side lamps (separate control). [See here for how I control these lights in HA](https://github.com/rtclauss/hass-config/blob/main/packages/zigbee_zwave.yaml)~~
* [Electro Llama ZZH Stick](https://electrolama.com/projects/zig-a-zig-ah/) for Zigbee2MQTT
    * Philips Hue (bulbs and light strip)
    * [Ealon Halo LED Downlights](https://www.zigbee2mqtt.io/devices/RL460WHZHA69.html#eaton%252Fhalo%2520led-rl460whzha69)
    * [Enbrighten 43100 Outdoor Switch](https://www.zigbee2mqtt.io/devices/43100.html#enbrighten-43100)
    * [Sengled E1C-NB7](https://www.zigbee2mqtt.io/devices/E1C-NB7.html#sengled-e1c-nb7) -  Energy reporting switch!
    * [Ikea FYRTUR Blinds](https://www.zigbee2mqtt.io/devices/E1757.html#ikea-e1757). Hacked to fit my smaller windows. [Here for details.](https://www.youtube.com/watch?v=Y3wts5blIJc)
    * [Ikea Tradfri outlet](https://www.zigbee2mqtt.io/devices/E1603_E1702_E1708.html#ikea-e1603%252Fe1702%252Fe1708)
    * Lutron Pico LZL-4B-WH-L01 Connected Bulb Remote for resetting bulbs
    * [EcoSmart 60-Watt Equivalent A19 Dimmable SMART LED Light Bulb Tunable White](https://www.homedepot.com/p/EcoSmart-60-Watt-Equivalent-A19-Dimmable-SMART-LED-Light-Bulb-Tunable-White-2-Pack-A9A19A60WESDZ02/309683612). Replaced the GE Link LED Bulb in most cases. Used with [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting) from HACS.
    * [Xiaomi Aqara Motion Sensors](https://www.zigbee2mqtt.io/devices/RTCGQ11LM.html#xiaomi-rtcgq11lm)
    * [Xiaomi Aqara Button](https://www.zigbee2mqtt.io/devices/WXKG01LM.html#xiaomi-wxkg01lm)
    * [Xiaomi Aqara Temperature Sensors](https://www.zigbee2mqtt.io/devices/WSDCGQ11LM.html#xiaomi-wsdcgq11lm)
    * [Xiaomi Window/Door Sensors](https://www.zigbee2mqtt.io/devices/RTCGQ11LM.html#xiaomi-rtcgq11lm)
    * [Xiami New Window/Door Sensors](https://www.zigbee2mqtt.io/devices/MCCGQ11LM.html#xiaomi-mccgq11lm)
    * [Xiaomi Leak Sensors](https://www.zigbee2mqtt.io/devices/SJCGQ11LM.html#xiaomi-sjcgq11lm)
    * [Xiaomi Aqara Cube](https://www.zigbee2mqtt.io/devices/MFKZQ01LM.html#xiaomi-mfkzq01lm)
    * Xiaomi Vibration Sensor
    * [SmartThings Presence Sensor](https://www.zigbee2mqtt.io/devices/STS-PRS-251.html#smartthings-sts-prs-251). Hacked to use 2AA Batteries instead of the coin battery. [Details on this upgrade](https://community.smartthings.com/t/presence-sensor-battery-upgrade/79737).
    * SmartThings Motion Sensor
    * ~~[Hampton Bay (King of Fans)](https://www.homedepot.com/p/Hampton-Bay-Universal-Wink-Enabled-White-Ceiling-Fan-Premier-Remote-Control-99432/206591100)~~ - These devices are very particular about what they will initially pair with.  I moved the NUC to the same room as the fans for the initial pairing.  After they were on the network they communicate over the Zigbee mesh proper. I recommend opening up the unit to check if the Zigbee antenna is firmly seated on the board.  You can also replace the small antenna with something like (this on Amazon)[https://www.amazon.com/gp/product/B077SVP7PN/ref=ppx_yo_dt_b_asin_title_o08_s00?ie=UTF8&psc=1].
    * [Peanut Zigbee Smart Plug](https://www.zigbee2mqtt.io/devices/PP-WHT-US.html#securifi-pp-wht-us) - Used to control the lava lamp in my office. Does not require Almond hub and does pair via ZHA.  Also act as more reliable repeaters for the Hampton Bay/KoF fans.  See [this blog post](http://diysoldier.com/hampton-bay-smart-ceiling-fan-and-light-control/), [this SmartThings Community thread](https://community.smartthings.com/t/hampton-bay-zigbee-fan-controller/47463/476) and [this reddit thread](https://www.reddit.com/r/SmartThings/comments/a3pbnz/peanut_smartplug_best_smart_plug_ive_found_for_10/) for more information. If you update the firmware to the latest version and have a lot of these plugs on your network you may see them randomly toggle on-off at random times.
      * Lava Lamp
      * Christmas Lights
      * Sump Pump
* [Bond Bridge](https://bondhome.io/product/bond-bridge/) to control ceiling fans (and maybe more!)
* [Good Earth LED Lighting panels](https://www.lowes.com/pd/Good-Earth-Lighting-1-Ft-x-4-Ft-Smart-WIFI-LED-Flush-Mount-Light-Flat-Panel-Black/1003017948) - [Local Tuya](https://github.com/rospogrigio/localtuya)
* Rachio for sprinklers
* MyQ Garage Door
* Unifi nanoHD-AP
* Unifi U6-Pro
* Unifi US-8
* Unifi Dream Machine Pro
* ~~[Generic OBDII GPRS Real Time Tracker](https://www.aliexpress.com/item/32981833499.html?spm=a2g0s.9042311.0.0.1bfa4c4dpn9kUy)~~
* [Custom Tesla Integration](https://github.com/alandtse/tesla)
* [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting)

**AppDaemon Apps:**
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
