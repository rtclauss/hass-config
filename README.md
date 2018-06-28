# The Brewery Home Assistant Configuration 🍺
[![Build Status](https://travis-ci.org/rtclauss/hass-config.svg?branch=master)](https://travis-ci.org/rtclauss/hass-config)

[Home Assistant](https://home-assistant.io/) configuration files (YAMLs) and [AppDaemon](https://appdaemon.readthedocs.io/en/latest/) apps.

I have Home Assistant running on a [Raspberry Pi 3]().

Software on the pi:
* [Home Assistant](https://home-assistant.io/) via [Hass.io](https://www.home-assistant.io/hassio/)
* Running in Hass.io
  * [AppDaemon](https://community.home-assistant.io/t/community-hass-io-add-on-appdaemon3/41261?u=frenck)
  * [Bluetooth BCM43xx](https://home-assistant.io/addons/bluetooth_bcm43xx/)
  * [IDE](https://community.home-assistant.io/t/community-hass-io-add-on-ide-based-on-cloud9/33810?u=frenck)
  * [Mosquitto Broker](https://home-assistant.io/addons/mosquitto/)
  * [Pi-hole](https://community.home-assistant.io/t/community-hass-io-add-on-pi-hole/33817?u=frenck)
  * [SmartThings MQTT Bridge](https://github.com/stjohnjohnson/smartthings-mqtt-bridge)
  * [esphomeyaml](https://esphomelib.com/esphomeyaml/index.html)

**Devices in Use:**
* Apple/iOS Devices - [iPhone X](), [iPad Pro]()
* [Nest Thermostat]()
* [Amazon Echo](http://amzn.to/2i6mShX)
* [Amazon Echo Dot Gen 2](http://amzn.to/2hvCexj)
* [Amazon Fire TV](http://amzn.to/2iD9uPx)
* [Philips Hue (Gen 2)](http://amzn.to/2hvyzzK)
* [Philips Hue Motion](http://amzn.to/2iD7jLX)
* [SmartThings Hub (Gen 1)]()
* [Wink Hub (Gen 1)]()
* Xiaomi Aqara Motion Sensors
* Xiaomi Aqara Button
* Xiaomi Aqara Temperature Sensors
* Xiaomi Window/Door Sensors
* Xiaomi Dafang Cameras running [custom firmware](https://github.com/EliasKotlyar/Xiaomi-Dafang-Hacks)
* HUSBZB-1 ZigBee/Z-Wave Stick
* Xiaomi MiFlora
* SmartThings Presense Sensor
* SmartThings Motion Sensor
* Leviton Switch Vizia RF+
* Leviton Vizia + Digital Coordinating Remote Switch
* GE Z-Wave Wireless Smart Lighting Control Outdoor Module

**AppDaemon Apps:**
* [Bayesian Device Tracker](appdaemon/apps/tracker.py) - Merges GPS location info with bayesian binary sensor to give a ground-truth location information.
* [Lighting Fade-In](appdaemon/apps/brighten_lights.py) - Fades in lights from `off` over a pre-defined interval on a work (non-weekend, non-holiday) day.
