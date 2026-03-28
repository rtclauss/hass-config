# Device Inventory

This file tracks available or unused smart-home devices that can be repurposed for Home Assistant planning.

## How To Use

- `quantity` is the number of available devices on hand.
- `brand` and `model` should use the canonical product name when possible.
- `technology` is the transport or protocol used by the device.
- `possible_home_assistant_domain` is the best-fit HA domain or control surface for automation planning.
- `battery` is the primary battery form factor, or `n/a` for line-powered devices.
- `cells_per_device` is the number of cells installed in each device.
- `notes` can capture useful behavior, constraints, or likely uses.

## Inventory

| Quantity | Brand | Model | Technology | Possible Home Assistant Domain | Battery | Cells / Device | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | IKEA | INSPELNING smart plug | Zigbee | `switch` | `n/a` | 0 | Smart plug with energy monitoring; useful for appliance control, power-based automations, and Zigbee routing. |
| 4 | IKEA | RODRET wireless dimmer | Zigbee | `button` | `AAA` | 1 | Battery remote for lighting scenes and manual overrides. Best treated as a scene controller or trigger source. |
| 8 | Philips Hue | White bulbs | Zigbee | `light` | `n/a` | 0 | Groupable bulbs for rooms, paths, bedtime lighting, and adaptive light scenes. |
| 6 | Aqara | Motion Sensor (RTCGQ11LM) | Zigbee | `binary_sensor` | `CR2450` | 1 | PIR motion sensor for occupancy, entry-path lighting, and room-level presence automations. |
| 2 | Xiaomi | Motion Sensor (RTCGQ01LM) | Zigbee | `binary_sensor` | `CR2450` | 1 | Legacy Xiaomi motion sensor for low-profile occupancy detection. |
| 8 | Aqara | Cube Controller (MKZQ01LM / MFKZQ01LM) | Zigbee | `sensor` | `CR2450` | 1 | Gesture-based scene controller. Issue #202 listed `mkzq01lm`; this row maps it to the Aqara cube family. |
| 2 | Aqara | Vibration Sensor (DJT11LM) | Zigbee | `binary_sensor` | `CR2032` | 1 | Vibration, knock, and tilt sensor for mailbox, drawer, appliance, or tamper automations. |
| 6 | Aqara | Temperature and Humidity Sensor (WSDCGQ11LM) | Zigbee | `sensor` | `CR2032` | 1 | Compact room climate sensor for HVAC balancing, humidity alerts, and occupancy context. |
| 4 | Ecolink | FireFighter | Non-Zigbee RF / verify SKU | `binary_sensor` | `CR123A` | 1 | Audio listener for existing smoke and CO alarms. Issue #202 labeled this Zigbee, but Ecolink FireFighter devices are typically not Zigbee. |
| 3 | Aqara | Door and Window Sensor (MCCGQ11LM) | Zigbee | `binary_sensor` | `CR1632` | 1 | Contact sensor for doors, windows, drawers, closets, and gate-style state tracking. |
| 1 | Xiaomi | Door and Window Sensor (MCCGQ01LM) | Zigbee | `binary_sensor` | `CR1632` | 1 | Legacy Xiaomi contact sensor for smaller door and window openings. |
| 1 | Aqara | Wireless Mini Switch (WXKG11LM) | Zigbee | `button` | `CR2032` | 1 | Single-button trigger source for scenes, shortcuts, bedside controls, or alerts. |
| 1 | Xiaomi | Mi Wireless Switch (WXKG01LM) | Zigbee | `button` | `CR2032` | 1 | Legacy Xiaomi single-button remote for scene triggers and manual overrides. |
| 4 | Aqara | Water Leak Sensor (SJCGQ11LM) | Zigbee | `binary_sensor` | `CR2032` | 1 | Leak detector for sinks, toilets, utility areas, and moisture-triggered shutoff automations. |
| 4 | IKEA | BADRING water leakage sensor | Zigbee | `binary_sensor` | `AAA` | 1 | Water leak sensor suited for laundry, utility, and under-sink placement. |
| 2 | IKEA | BILRESA remote control with smart scroll wheel | Thread | `button` | `AAA` | 2 | Thread remote with a scroll wheel that can be repurposed for lighting, shades, or media volume scenes. |
| 2 | IKEA | SYMFONISK sound remote | Zigbee | `button` | `CR2032` | 1 | Assumes the original Zigbee sound remote generation; update this row if these are Gen 2 remotes that use `2 x AAA`. |
| 4 | IKEA | PARASOLL door/window sensor | Zigbee | `binary_sensor` | `AAA` | 1 | Contact sensor for doors, windows, closets, and away-mode checks. Useful for open-window alerts and entry-point lighting. |
| 8 | Espressif | ESP32 development board | Wi-Fi, Bluetooth | `sensor` | `n/a` | 0 | General-purpose MCU for ESPHome nodes, BLE proxies, or custom sensor and switch firmware. Best domain depends on what you flash onto it. |

## Battery Planning

This table turns the per-device battery metadata into a stock plan. The `buffer` column is the extra pool to keep ready for hot-swaps while rechargeables are charging or while replacements are in transit.

| Battery | Devices / Rows | Installed Cells | Buffer | Total To Keep Ready | Notes |
| --- | --- | --- | --- | --- | --- |
| `AAA` | `RODRET`, `BADRING`, `BILRESA`, `PARASOLL` | 16 | 8 | 24 | IKEA explicitly recommends rechargeable `AAA` cells for several of these devices, so a half-set buffer is practical. |
| `CR2450` | `RTCGQ11LM`, `RTCGQ01LM`, cube controller | 16 | 8 | 24 | Use this as spare stock unless you verify a compatible rechargeable `2450` workflow for every affected device. |
| `CR2032` | `DJT11LM`, `WSDCGQ11LM`, `WXKG11LM`, `WXKG01LM`, `SJCGQ11LM`, `SYMFONISK` | 16 | 8 | 24 | Rechargeable `2032`-format cells exist, but standard primary `CR2032` cells are not rechargeable. Verify voltage, thickness, and charge method before substituting chemistries. |
| `CR1632` | `MCCGQ11LM`, `MCCGQ01LM` | 4 | 4 | 8 | Smaller coin cell used by the door sensors. Keeping a full spare round avoids scattered one-off replacements. |
| `CR123A` | `FireFighter` | 4 | 4 | 8 | Treat as disposable primary lithium stock unless the exact Ecolink SKU and charger plan support something else. |

## Battery Assumptions

- `SYMFONISK` is counted as the original Zigbee sound remote (`1 x CR2032`). If these are Gen 2 remotes, move `2` installed cells from `CR2032` to `AAA`.
- `MKZQ01LM` in issue #202 appears to refer to the Aqara cube controller family (`MKZQ01LM` CN / `MFKZQ01LM` global), which uses a single `CR2450`.
- The `FireFighter` row reflects the Ecolink FireFighter battery family (`CR123A`), but the exact protocol and SKU should be verified because issue #202 labeled it as Zigbee.

## Automation Ideas

- Map each `RODRET` remote to a nearby Hue bulb group for on/off, dim, and scene cycling.
- Use `INSPELNING` power monitoring to detect appliance state changes and notify when a load starts or finishes.
- Use the Hue white bulbs as a dedicated hallway or bedroom group with adaptive lighting, bedtime shutdown, and low-brightness night scenes.
- Use one or more `INSPELNING` plugs as smart fail-safes for devices that should turn off when the house enters away mode.
- Use the remotes and bulbs together to create a physical "all lights off" exit routine near doors or bedrooms.
- Use `Aqara` motion sensors for hallway, bathroom, stair, and closet occupancy automations with restart-mode lighting.
- Use the Aqara/Xiaomi temperature sensors to build room-by-room humidity and temperature drift alerts for HVAC tuning.
- Use the Aqara/Xiaomi mini switches, cube controllers, `BILRESA`, and `SYMFONISK` remotes as scene, media, or shade controllers without touching the app.
- Use the Aqara and IKEA leak sensors under sinks, near the water heater, and behind toilets for faster water-loss detection.
- Use the Ecolink `FireFighter` sensors to surface legacy smoke or CO alarms into Home Assistant notifications and alarm flows.
- Use `PARASOLL` contact sensors to pause HVAC when windows open, send door-left-open alerts, and trigger entry/exit lighting.
- Use `ESP32` boards as ESPHome BLE proxies or custom sensor nodes in weak-signal areas of the house.

## Update Rule

When more examples are provided, append rows here and keep the model names canonical. If a device can reasonably fit more than one Home Assistant domain, prefer the control surface that matches how it is actually used.
