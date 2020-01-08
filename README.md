# The Brewery Home Assistant Configuration 🍺
[![Build Status](https://travis-ci.org/rtclauss/hass-config.svg?branch=master)](https://travis-ci.org/rtclauss/hass-config)

[Home Assistant](https://home-assistant.io/) configuration files (YAMLs) and [AppDaemon](https://appdaemon.readthedocs.io/en/latest/) apps.

I have Home Assistant running on an [Intel NUC]().  This has been a work in progress since Nov 2015 (HA v0.7 or earlier).

Software on the NUC:
* [Home Assistant](https://home-assistant.io/) via [Hass.io](https://www.home-assistant.io/hassio/)
* Running in Hass.io
  * [ADB](https://github.com/hassio-addons/addon-adb)
  * [AppDaemon](https://community.home-assistant.io/t/community-hass-io-add-on-appdaemon3/41261?u=frenck)
  * [IDE](https://community.home-assistant.io/t/community-hass-io-add-on-ide-based-on-cloud9/33810?u=frenck)
  * [Mosquitto Broker](https://home-assistant.io/addons/mosquitto/)
  * [Traccar](https://github.com/hassio-addons/addon-traccar)
  * [JupyterLab Lite](https://github.com/hassio-addons/addon-jupyterlab-lite) Only sometimes when I need to figure out event correllation
  * [esphomeyaml](https://esphomelib.com/esphomeyaml/index.html) - Not used anymore

**Devices in Use:**
* Apple/iOS Devices - [iPhone XS](), [iPad Pro]()
* [Nest Thermostat]()
* [Amazon Echo](http://amzn.to/2i6mShX)
* [Amazon Echo Dot Gen 2](http://amzn.to/2hvCexj)
* [Amazon Fire TV](http://amzn.to/2iD9uPx)
* Lutron Pico LZL-4B-WH-L01 Connected Bulb Remote
* Xiaomi Dafang Cameras running [custom firmware](https://github.com/EliasKotlyar/Xiaomi-Dafang-Hacks)
* Xiaomi MiFlora
* ESP8266 with [VL53L0X](https://www.amazon.com/gp/product/B07F3RH7TC/ref=ppx_yo_dt_b_asin_title_o00_s00?ie=UTF8&psc=1) to measure salt level in water softener. See [this commit](https://github.com/rtclauss/hass-config/commit/85b1eade336c0fc94031241b494203fb55b3a7d8) for more info. 
* HUSBZB-1 Zigbee/Z-Wave Stick (for Z-Wave and Zigbee)
  * Z-Wave 
    * [Leviton Switch Vizia RF+ VRS05-1LZ](https://www.amazon.com/gp/product/B001HT6NKO/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) - 3 wire 3-way switch.
    * [Leviton Vizia + Digital Coordinating Remote Switch](https://www.amazon.com/gp/product/B001HT4M70/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1)
    * GE Z-Wave Wireless Smart Lighting Control Outdoor Module
    * GE Z-Wave Wireless Smart Lighting Control Appliance Switch
    * Bed presense sensor: [Ecolink Z-Wave door/window sensor](https://www.amazon.com/Ecolink-Intelligent-Technology-Operated-DWZWAVE2-ECO/dp/B00HPIYJWU) mated with [Ideal pressure mat](https://www.amazon.com/Ecolink-Intelligent-Technology-Operated-DWZWAVE2-ECO/dp/B00HPIYJWU)
    * [GoControl Z-Wave Plug-in Dimmer](https://www.amazon.com/GoControl-Z-Wave-Plug-Dimmer-Module/dp/B00E1OXK3A/)
    * [Zooz Z-Wave Plus S2/ZEN26](https://www.amazon.com/gp/product/B07K1T8Z74/ref=ppx_yo_dt_b_asin_title_o00_s00?ie=UTF8&psc=1)
  * Zigbee
    * Philips Hue (bulbs and light strip)
    * GE Link Smart LED Bulbs
    * Xiaomi Aqara Motion Sensors
    * Xiaomi Aqara Button
    * Xiaomi Aqara Temperature Sensors
    * Xiaomi Window/Door Sensors
    * Xiaomi Vibration Sensor
    * SmartThings Presence Sensor
    * SmartThings Motion Sensor
    * [Hampton Bay (King of Fans)](https://www.homedepot.com/p/Hampton-Bay-Universal-Wink-Enabled-White-Ceiling-Fan-Premier-Remote-Control-99432/206591100) - These devices are very particular about what they will initially pair with.  I moved the NUC to the same room as the fans for the initial pairing.  After they were on the network they communicate over the Zigbee mesh proper.
    * Peanut Zigbee Smart Plug - Used to control the lava lamp in my office. Does not require Almond hub and does pair via ZHA.  Also act as more reliable repeaters for the Hampton Bay/KoF fans.  See [this blog post](http://diysoldier.com/hampton-bay-smart-ceiling-fan-and-light-control/), [this SmartThings Community thread](https://community.smartthings.com/t/hampton-bay-zigbee-fan-controller/47463/476) and [this reddit thread](https://www.reddit.com/r/SmartThings/comments/a3pbnz/peanut_smartplug_best_smart_plug_ive_found_for_10/) for more information.

* Unifi nanoHD-AP
* Unifi USG
* [Generic OBDII GPRS Real Time Tracker](https://www.aliexpress.com/item/32981833499.html?spm=a2g0s.9042311.0.0.1bfa4c4dpn9kUy)


**AppDaemon Apps:**
* [Bayesian Device Tracker](appdaemon/apps/tracker.py) - Merges GPS location info with bayesian binary sensor to give ground-truth location tracking.  Uses bayesian data to eliminate red-herrings when arriving at home.  Could be extended to other zones if you have multiple `device_tracker`s 
* [Lighting Fade-In](appdaemon/apps/brighten_lights.py) - Fades in lights from `off` over a pre-defined interval on a work (non-weekend, non-holiday) day.
* [Music Fade-in](appdaemon/apps/fade_in_music.py) - Fades in music when I wake up in the morning
* [deConz button events](appdaemon/apps/deconz_helper.py) - Translates Xiaomi button events into a generic sensor.
* [Magic Cube](appdaemon/apps/magic_cube.py) - Translates Xiaomi Magic Cube events into actions controlling my living room Hue lights
* [Automatic event helper](appdaemon/apps/automatic_helper.py) - Similar to deCONZ helper this translates matic events into a generic sensor.
* [Nest Travel helper](appdaemon/apps/nest_travel_helper.py) - When driving long distances the Nest will switch from heating/cooling back to away mode if you don't arrive home soon enough.  This listens for those changes and keeps Nest from switching back to away mode.

**Apple Shortcuts**
* [Set wakeup time](https://www.icloud.com/shortcuts/61be3701823f444dbae0de1626020025) - Slowly turn on bedroom lights in the morning before a meeting
