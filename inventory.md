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

## Configured Battery Devices

This table summarizes battery-powered devices that are already represented in the active Home Assistant configuration. Counts come from live battery entities where available plus the currently defined MiFlora-backed plant package entries.

| Quantity | Brand | Model | Technology | Possible Home Assistant Domain | Battery | Cells / Device | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | Aqara | Motion Sensor (RTCGQ11LM) | Zigbee | `binary_sensor` | `CR2450` | 1 | Six installed Zigbee motion sensors currently expose battery percentages in Home Assistant. |
| 1 | Aqara | Motion and Light Sensor P2 | Matter | `binary_sensor` | `CR2450` | 1 | Counted from `sensor.aqara_motion_and_light_sensor_p2_battery`; Home Assistant also exposes a `battery_type` entity confirming `CR2450`. |
| 1 | Aqara | Cube Controller (MKZQ01LM / MFKZQ01LM) | Zigbee | `sensor` | `CR2450` | 1 | Live Home Assistant device reports model `Cube`; counted with the Aqara cube family used in the spare inventory section. |
| 8 | Aqara | Temperature and Humidity Sensor (WSDCGQ11LM) | Zigbee | `sensor` | `CR2032` | 1 | Eight configured room climate sensors currently report battery values in Home Assistant. |
| 1 | Aqara | Vibration Sensor (DJT11LM) | Zigbee | `binary_sensor` | `CR2032` | 1 | Laundry washer vibration node. |
| 1 | Aqara | Water Leak Sensor (SJCGQ11LM) | Zigbee | `binary_sensor` | `CR2032` | 1 | Basement unfinished leak node. |
| 1 | Aqara | Door and Window Sensor (MCCGQ11LM) | Zigbee | `binary_sensor` | `CR1632` | 1 | Hall garage entry contact sensor. |
| 1 | Xiaomi | Mi Wireless Switch (WXKG01LM) | Zigbee | `button` | `CR2032` | 1 | Hall button scene trigger. |
| 8 | IKEA | PARASOLL door/window sensor | Zigbee | `binary_sensor` | `AAA` | 1 | Kitchen, dining room, powder room, and mailbox contact sensors are already installed. |
| 1 | IKEA | RODRET wireless dimmer | Zigbee | `button` | `AAA` | 1 | One live RODRET dimmer is paired today; the spare inventory section tracks four more. |
| 2 | IKEA | SOMRIG shortcut button | Zigbee | `button` | `AAA` | 1 | East and west bedside shortcut buttons. |
| 2 | IKEA | TRADFRI remote control | Zigbee | `button` | `CR2032` | 1 | Office light buttons are the older CR2032-powered TRADFRI remote generation, not STYRBAR. |
| 2 | IKEA | SYMFONISK sound remote, gen 2 | Zigbee | `button` | `AAA` | 2 | The installed Sonos remotes are explicitly the Gen 2 model, so each uses `2 x AAA`. |
| 2 | IKEA | FYRTUR roller blind, block-out | Zigbee | `cover` | `FYRTUR battery pack` | 1 | Counted as one removable rechargeable pack per blind. |
| 1 | SmartThings | Arrival sensor | Zigbee | `binary_sensor` | `AA` | 2 | README documents this sensor as modified to use `2 x AA` instead of the stock coin cell. |
| 5 | ecobee Inc. | Remote occupancy and temperature sensor (EBERS41) | Proprietary RF / HomeKit | `sensor` | `CR2477` | 1 | Guest room, bedroom, den, basement, and office sensors report battery through HomeKit Controller. |
| 12 | Xiaomi | MiFlora plant sensor | Bluetooth LE | `plant` | `CR2032` | 1 | Counted from the twelve active plant definitions in `packages/plants.yaml`; assumes the current plant-monitor fleet is still MiFlora-family hardware. |

## Battery Planning

This table combines the spare inventory above with the currently configured battery fleet. The `swap / charge overhead` column is the extra stock to keep ready so a low-battery alert never has to wait on a charger cycle, shipping delay, or a special-order cell.

| Battery | Kind | Inventory Cells | Configured Cells | Swap / Charge Overhead | Total To Keep Ready | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `AAA` | Rechargeable cylindrical | 16 | 15 | 16 | 47 | Covers deployed window sensors and remotes plus a half-set rechargeable buffer for same-day swaps. |
| `AA` | Rechargeable cylindrical | 0 | 2 | 2 | 4 | Keep one charged pair ready for the modified arrival sensor. |
| `FYRTUR battery pack` | Rechargeable pack | 0 | 2 | 1 | 3 | One charged spare pack keeps a blind online while the other pack recharges. |
| `CR2450` | Primary coin cell | 16 | 8 | 6 | 30 | Shared across the legacy motion sensors, the cube, and the Matter P2 motion sensor. |
| `CR2032` | Primary coin cell | 16 | 25 | 11 | 52 | This becomes the largest family once the installed climate sensors, plant sensors, TRADFRI remotes, and small Aqara/Xiaomi nodes are included. |
| `CR1632` | Primary coin cell | 4 | 1 | 3 | 8 | Small but easy-to-forget door-sensor cell; keep a few ahead of failures. |
| `CR2477` | Primary coin cell | 0 | 5 | 3 | 8 | Niche ecobee sensor cell that is worth stocking instead of special-ordering after a failure. |
| `CR123A` | Primary cylindrical lithium | 4 | 0 | 4 | 8 | Keep a full spare round for the FireFighter stock because this cell is less interchangeable with the rest of the house. |
| `TOTAL` | 8 battery families / 4 kinds | 56 | 58 | 46 | 160 | Kinds in use: rechargeable cylindrical cells, rechargeable packs, primary coin cells, and primary cylindrical lithium cells. |

## Battery Assumptions

- `SYMFONISK` spare inventory row is still counted as the original Zigbee sound remote (`1 x CR2032`), but the currently configured Home Assistant devices are Gen 2 remotes (`2 x AAA` each).
- `TRADFRI remote control` in Home Assistant is counted as the older `CR2032`-powered remote, not a later `AAA`-powered STYRBAR-style remote.
- `MiFlora plant sensor` assumes the current plant-monitor fleet behind `packages/plants.yaml` still uses the Xiaomi MiFlora / Flower Care battery profile (`1 x CR2032` each).
- `SmartThings Arrival sensor` uses the README-documented `2 x AA` battery mod in the current setup.
- `FYRTUR` is counted as one removable rechargeable battery pack per blind, with one extra charged pack kept as swap coverage.
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
