# Device Inventory

This file tracks available or unused smart-home devices that can be repurposed for Home Assistant planning.

## How To Use

- `quantity` is the number of available devices on hand.
- `brand` and `model` should use the canonical product name when possible.
- `technology` is the transport or protocol used by the device.
- `possible_home_assistant_domain` is the best-fit HA domain or control surface for automation planning.
- `notes` can capture useful behavior, constraints, or likely uses.

## Inventory

| Quantity | Brand | Model | Technology | Possible Home Assistant Domain | Notes |
| --- | --- | --- | --- | --- | --- |
| 4 | IKEA | INSPELNING smart plug | Zigbee | `switch` | Smart plug with energy monitoring; useful for appliance control, power-based automations, and Zigbee routing. |
| 4 | IKEA | RODRET wireless dimmer | Zigbee | `button` | Battery remote for lighting scenes and manual overrides. Best treated as a scene controller or trigger source. |
| 8 | Philips Hue | White bulbs | Zigbee | `light` | Groupable bulbs for rooms, paths, bedtime lighting, and adaptive light scenes. |

## Automation Ideas

- Map each `RODRET` remote to a nearby Hue bulb group for on/off, dim, and scene cycling.
- Use `INSPELNING` power monitoring to detect appliance state changes and notify when a load starts or finishes.
- Use the Hue white bulbs as a dedicated hallway or bedroom group with adaptive lighting, bedtime shutdown, and low-brightness night scenes.
- Use one or more `INSPELNING` plugs as smart fail-safes for devices that should turn off when the house enters away mode.
- Use the remotes and bulbs together to create a physical "all lights off" exit routine near doors or bedrooms.

## Update Rule

When more examples are provided, append rows here and keep the model names canonical. If a device can reasonably fit more than one Home Assistant domain, prefer the control surface that matches how it is actually used.
