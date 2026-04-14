# EV Charging Tariff

This document describes the EV-specific charging tariff added in `packages/utilities.yaml`.

## Purpose

The rest of the house stays on the existing seasonal energy rate model.

The Tesla charger now has its own Dakota Electric time-of-use model so:

- EV charging costs are tracked separately from whole-home electricity usage
- the Tesla departure planner can react to the EV tariff instead of the house tariff
- the Tesla dashboards can show the current EV rate and EV charging cost totals

## Source Data

### Rate schedule

This implementation follows the Dakota Electric EV time-of-use schedule from the packet provided by the user:

- off-peak: `$0.0755/kWh`
- mid-peak non-summer: `$0.1238/kWh`
- mid-peak summer: `$0.1377/kWh`
- on-peak: `$0.4420/kWh`

Schedule:

- weekdays before `08:00` and from `21:00` onward: off-peak
- weekdays `08:00` to `16:00`: mid-peak
- weekdays `16:00` to `21:00`: on-peak
- weekends and Minnesota holidays: off-peak all day

Summer is treated as June 1 through September 30, matching the existing seasonal house tariff split.

### Energy source

EV usage is measured from:

- `sensor.nigori_energy_added`

That Tesla entity reports `kWh`, `device_class: energy`, and `state_class: total_increasing`, so it can back `utility_meter` helpers.

Important limitation:

- this measures energy added to the car battery, not wall-side charger losses

If a dedicated EVSE energy meter is added later, the EV utility meters should switch to that meter instead.

## Entities

### Current tariff state

- `select.hourly_ev_charging`
- `select.daily_ev_charging`
- `select.monthly_ev_charging`
- `input_number.ev_electrical_rate`
- `sensor.ev_charging_tariff`
- `sensor.ev_charging_tariff_rate`

The `switch_ev_charging_tariff` automation keeps those entities aligned to the schedule.

### EV charging utility meters

- `sensor.hourly_ev_charging_*`
- `sensor.daily_ev_charging_*`
- `sensor.monthly_ev_charging_*`

Tariffs:

- `off_peak`
- `mid_peak`
- `on_peak`

### Derived EV totals

- `sensor.daily_ev_charging_energy`
- `sensor.monthly_ev_charging_energy`
- `sensor.daily_ev_charging_cost`
- `sensor.monthly_ev_charging_cost`

## UI

The EV tariff is surfaced on both Tesla dashboard paths:

- storage mode: `.storage/lovelace.ryan_new_mushroom`, view path `tesla-v2`
- YAML mode: `lovelace/tiles/tiles_tesla_charging.yaml`
- storage mode energy view: `.storage/lovelace.ryan_new_mushroom`, view path `energy`

The Tesla dashboards now show:

- current EV tariff
- current EV rate
- daily EV energy and cost
- monthly EV energy and cost
- a planner-decision summary card

## Built-in Energy Panel

Home Assistant's built-in Energy panel can use the EV tariff, but it should be configured as two separate grid-consumption sources.

Use these entities in `Settings > Dashboards > Energy`:

- house without EV:
  - energy: `sensor.house_electrical_meter_non_ev`
  - current price: `sensor.house_electrical_rate`
- EV charging:
  - energy: `sensor.nigori_energy_added`
  - current price: `sensor.ev_charging_tariff_rate`

Important:

- do not use `sensor.house_electrical_meter` for grid consumption if you add the EV source separately, or EV charging will be counted twice
- `sensor.house_electrical_meter_non_ev` is derived as whole-house energy minus `sensor.nigori_energy_added`
- this keeps the built-in Energy panel aligned with the EV tariff, but it still reflects battery-added EV energy rather than wall-side charging losses

The built-in Energy panel preferences are not tracked in this repository, so the panel still needs to be updated manually in the Home Assistant UI after this config is deployed.

## Validation

Recommended validation after EV tariff changes:

```bash
yamllint -d "{extends: relaxed, rules: {line-length: disable, empty-lines: disable, truthy: disable}}" \
  configuration.yaml automations.yaml blueprints packages zigbee2mqtt lovelace

uv run --python 3.14.2 --with homeassistant==2026.3.3 \
  python -m homeassistant --config "$PWD" --script check_config
```
