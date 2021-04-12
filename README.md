# The Brewery Home Assistant Configuration 🍺
[![Build Status](https://travis-ci.org/rtclauss/hass-config.svg?branch=master)](https://travis-ci.org/rtclauss/hass-config)

[Home Assistant](https://home-assistant.io/) configuration files (YAMLs) and [AppDaemon](https://appdaemon.readthedocs.io/en/latest/) apps.

I have Home Assistant running on an [Intel NUC]().  This has been a work in progress since Nov 2015 (HA v0.7 or earlier).

I use the new dashboards in 0.107 to create a [dashboard for guests](https://github.com/rtclauss/hass-config/blob/master/ui-guest.yaml) on an Amazon Fire Tab running Fully Kiosk Browser.

Software on the NUC:
* [Home Assistant](https://home-assistant.io/) via [Hass.io](https://www.home-assistant.io/hassio/)
* Running in Hass.io
  * [ADB](https://github.com/hassio-addons/addon-adb)
  * [AppDaemon](https://github.com/hassio-addons/addon-vscode)
  * [VSCode](https://github.com/hassio-addons/addon-vscode)
  * [Mosquitto Broker](https://home-assistant.io/addons/mosquitto/)
  * [Traccar](https://github.com/hassio-addons/addon-traccar) - Used with OBDII Sensor to track my car.
  * [JupyterLab Lite](https://github.com/hassio-addons/addon-jupyterlab-lite) Only sometimes when I need to figure out event correllation
  * [esphomeyaml](https://esphomelib.com/esphomeyaml/index.html) - Used for [Water Softener](https://github.com/rtclauss/hass-config/blob/master/packages/water_softener.yaml) and [Bed Occupancy Sensor](https://github.com/rtclauss/hass-config/blob/master/esphome/bedloadcell1.yaml)
  * ~[OpenZwave Beta]()~
  * [Zwave-JS](https://www.home-assistant.io/integrations/zwave_js)

**Devices in Use:**
* Apple/iOS Devices - [iPhone 12 Pro](), [iPad Pro]()
* ~[Nest Thermostat]()~ Replaced with Z-wave Thermostat and [Schedy](https://github.com/rtclauss/hass-config/blob/master/appdaemon/apps/schedy_heating.yaml)
* [Amazon Echo](http://amzn.to/2i6mShX)
* [Amazon Echo Dot Gen 2](http://amzn.to/2hvCexj)
* [Amazon Fire TV](http://amzn.to/2iD9uPx)
* Sonos One Speakers
* Xiaomi Dafang Cameras running [custom firmware](https://github.com/EliasKotlyar/Xiaomi-Dafang-Hacks)
* Xiaomi MiFlora
* ESP8266 with [VL53L0X](https://www.amazon.com/gp/product/B07F3RH7TC/ref=ppx_yo_dt_b_asin_title_o00_s00?ie=UTF8&psc=1) to measure salt level in [water softener](https://github.com/rtclauss/hass-config/blob/master/packages/water_softener.yaml). See [this commit](https://github.com/rtclauss/hass-config/commit/85b1eade336c0fc94031241b494203fb55b3a7d8) for more info. 
* HUSBZB-1 Zigbee/Z-Wave Stick (for Z-Wave and Zigbee)
  * Z-Wave 
    * [GoControl Z-Wave Thermostat](https://www.amazon.com/GoControl-Thermostat-Z-Wave-Battery-Powered-Works/dp/B00ZIRV40K)
    * [Leviton Switch Vizia RF+ VRS05-1LZ](https://www.amazon.com/gp/product/B001HT6NKO/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) - 3 wire 3-way switch.
    * [Leviton Vizia + Digital Coordinating Remote Switch](https://www.amazon.com/gp/product/B001HT4M70/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1)
    * GE Z-Wave Wireless Smart Lighting Control Outdoor Module
    * GE Z-Wave Wireless Smart Lighting Control Appliance Switch
    * ~~Bed presense sensor (2x): [Ecolink Z-Wave door/window sensor](https://www.amazon.com/Ecolink-Intelligent-Technology-Operated-DWZWAVE2-ECO/dp/B00HPIYJWU) mated with [Ideal pressure mat](https://www.amazon.com/Ecolink-Intelligent-Technology-Operated-DWZWAVE2-ECO/dp/B00HPIYJWU)~~ Replaced by custom solution below
    * [Bed Occupancy Sensor](https://community.home-assistant.io/t/bed-occupancy-sensor-using-parts-you-have/189490) Following N-I1's design but using a large, closed-cell foam sheet covered with copper foil on both sides.
    * [GoControl Z-Wave Plug-in Dimmer](https://www.amazon.com/GoControl-Z-Wave-Plug-Dimmer-Module/dp/B00E1OXK3A/)
    * [Zooz Z-Wave Plus S2/ZEN26](https://www.amazon.com/gp/product/B07K1T8Z74/ref=ppx_yo_dt_b_asin_title_o00_s00?ie=UTF8&psc=1)
    * [Inovelli ZSW31-SN Dimmer Switches](https://support.inovelli.com/portal/en/kb/articles/products-switches-dimmer-lzw31-sn-spec-sheet): These are great multifunctional dimmers which have disableable relays so you can control smart bulbs which are plugged in to the controlled socket. To disable the relay, click the Control button 8 times.  Then you use Z-Wave events to control the lights as you see fit.  I use this in my guest room to control the ceiling fan light (ceiling fan is controllable by chain) which is on the circuit and to control the two side lamps (separate control). [See here for how I control these lights in HA](https://github.com/rtclauss/hass-config/blob/master/packages/zigbee_zwave.yaml)
  * Zigbee
    * Philips Hue (bulbs and light strip)
    * ~~GE Link Smart LED Bulbs~~ Replaced due to poor antenna quality and humidity forming in the bulb
    * Lutron Pico LZL-4B-WH-L01 Connected Bulb Remote for resetting bulbs
    * [EcoSmart 60-Watt Equivalent A19 Dimmable SMART LED Light Bulb Tunable White](https://www.homedepot.com/p/EcoSmart-60-Watt-Equivalent-A19-Dimmable-SMART-LED-Light-Bulb-Tunable-White-2-Pack-A9A19A60WESDZ02/309683612). Replaced the GE Link LED Bulb in most cases. Used with [Circadian Lighting](https://github.com/claytonjn/hass-circadian_lighting) from HACS. [See here for how it's configured](https://github.com/rtclauss/hass-config/blob/master/packages/light.yaml#L1090)
    * Xiaomi Aqara Motion Sensors
    * Xiaomi Aqara Button
    * Xiaomi Aqara Temperature Sensors
    * Xiaomi Window/Door Sensors
    * Xiaomi Vibration Sensor
    * SmartThings Presence Sensor
    * SmartThings Motion Sensor
    * [Hampton Bay (King of Fans)](https://www.homedepot.com/p/Hampton-Bay-Universal-Wink-Enabled-White-Ceiling-Fan-Premier-Remote-Control-99432/206591100) - These devices are very particular about what they will initially pair with.  I moved the NUC to the same room as the fans for the initial pairing.  After they were on the network they communicate over the Zigbee mesh proper. I recommend opening up the unit to check if the Zigbee antenna is firmly seated on the board.  You can also replace the small antenna with something like (this on Amazon)[https://www.amazon.com/gp/product/B077SVP7PN/ref=ppx_yo_dt_b_asin_title_o08_s00?ie=UTF8&psc=1].
    * Peanut Zigbee Smart Plug - Used to control the lava lamp in my office. Does not require Almond hub and does pair via ZHA.  Also act as more reliable repeaters for the Hampton Bay/KoF fans.  See [this blog post](http://diysoldier.com/hampton-bay-smart-ceiling-fan-and-light-control/), [this SmartThings Community thread](https://community.smartthings.com/t/hampton-bay-zigbee-fan-controller/47463/476) and [this reddit thread](https://www.reddit.com/r/SmartThings/comments/a3pbnz/peanut_smartplug_best_smart_plug_ive_found_for_10/) for more information.
      * [Humidifier](https://www.amazon.com/dp/B002QAYJPO/) for the bedroom
      * Lava Lamp
      * Christmas Lights

* Unifi nanoHD-AP
* Unifi US-8
* ~~Unifi USG~~ Replaced with UDM-PRO after switching ISPs
* [Generic OBDII GPRS Real Time Tracker](https://www.aliexpress.com/item/32981833499.html?spm=a2g0s.9042311.0.0.1bfa4c4dpn9kUy)


**AppDaemon Apps:**
* [Bayesian Device Tracker](appdaemon/apps/tracker.py) - Merges GPS location info with bayesian binary sensor to give ground-truth location tracking.  Uses bayesian data to eliminate red-herrings when arriving at home.  Could be extended to other zones if you have multiple `device_tracker`s 
* [Lighting Fade-In](appdaemon/apps/brighten_lights.py) - Fades in lights from `off` over a pre-defined interval on a work (non-weekend, non-holiday) day.
* [Music Fade-in](appdaemon/apps/fade_in_music.py) - Fades in music when I wake up in the morning
* [deConz button events](appdaemon/apps/deconz_helper.py) - Translates Xiaomi button events into a generic sensor.
* [Magic Cube](appdaemon/apps/magic_cube.py) - Translates Xiaomi Magic Cube events into actions controlling my living room Hue lights
* [Automatic event helper](appdaemon/apps/automatic_helper.py) - Similar to deCONZ helper this translates matic events into a generic sensor.
* [Nest Travel helper](appdaemon/apps/nest_travel_helper.py) - When driving long distances the Nest will switch from heating/cooling back to away mode if you don't arrive home soon enough.  This listens for those changes and keeps Nest from switching back to away mode.
* [Schedy](appdaemon/apps/schedy_heating.yaml) - Replacement for Nest. Work in Progress.
* [Thermostat Stats](https://github.com/rtclauss/hass-config/blob/master/appdaemon/apps/thermostat_stats.py) - Gathers historical house temperature data.  Will feed into ML model to predict time to temp, etc.

**Apple Shortcuts**
* [Set wakeup time](https://www.icloud.com/shortcuts/61be3701823f444dbae0de1626020025) - [Slowly turn on bedroom lights in the morning before a meeting](https://github.com/rtclauss/hass-config/blob/master/packages/workday.yaml#L107)
