# Tesla Departure Planner

This document describes the Tesla departure planner added in `packages/car.yaml`.

## Purpose

The planner sets the Tesla charge limit and scheduled departure behavior based on:

- upcoming trips
- weekday/weekend alarm settings
- weather
- EV charging tariff/rate
- a manual max-range override

## Inputs

### Trip inputs

- `binary_sensor.upcoming_trip_charging`
- `sensor.waze_next_trip_distance`

If an upcoming trip exists, the planner uses trip start time plus Waze duration to determine a departure window.

### Alarm inputs

- `input_boolean.weekday_alarm_on`
- `input_boolean.weekend_alarm_on`
- `input_datetime.weekday_alarm`
- `input_datetime.weekend_alarm`

These drive non-trip next-morning departure planning.

### Weather inputs

- `sensor.outside_temperature`

Cold weather currently means `<= 20F`.

Cold weather increases departure buffer time and can justify preconditioning or a higher charge target.

### EV tariff inputs

- `select.daily_ev_charging`
- `select.hourly_ev_charging`
- `input_number.ev_electrical_rate`
- `sensor.ev_charging_tariff`
- `sensor.ev_charging_tariff_rate`

The EV charging tariff is separate from the rest of the house. It follows the Dakota Electric time-of-use schedule from the EV packet provided by the user:

- off-peak: `$0.0755/kWh`
- mid-peak non-summer: `$0.1238/kWh`
- mid-peak summer: `$0.1377/kWh`
- on-peak: `$0.4420/kWh`

Schedule:

- weekdays before `08:00` and from `21:00` onward: off-peak
- weekdays `08:00` to `16:00`: mid-peak
- weekdays `16:00` to `21:00`: on-peak
- weekends and Minnesota holidays: off-peak all day

The planner treats the tariff as "higher" when:

- the EV tariff is `on_peak`
- the numeric electrical rate is `>= 0.13`

This only affects the non-trip alarm top-off case. Trip charging and cold-weather cases still take priority.

### Manual override

- `input_boolean.long_range_travel`

This is the explicit max-range override surfaced on the Tesla dashboard.

When it is on, the planner pins the charge limit to `100%`.

## Outputs

### Charge limit

- `number.nigori_charge_limit`

Decision summary:

- long trip (`>= 90 mi`): `100%`
- other trip: `90%`
- alarm + cold weather: `90%`
- alarm + lower EV tariff: `85%`
- alarm + higher EV tariff: `80%`
- no plan: `80%`
- manual max-range override: `100%`

### Scheduled departure

Script:

- `script.tesla_set_precondition_schedule_time`

Behavior:

- enables Tesla scheduled departure when preconditioning is needed and a departure time exists
- disables Tesla scheduled departure when the planner no longer has a preconditioning plan to keep

### Notifications

The planner sends Tesla status notifications with a deep link to the storage dashboard Tesla view:

- `/ryan-new-mushroom/tesla-v2`

## UI locations

### Tesla dashboard

Storage-mode dashboard:

- `.storage/lovelace.ryan_new_mushroom`
- view path: `tesla-v2`
- companion storage energy view path: `energy`

Controls:

- `Max Range Override`
- `Use Daily Plan`
- `Planner Decision`
- `sensor.ev_charging_tariff`
- `sensor.ev_charging_tariff_rate`
- `sensor.daily_ev_charging_energy`
- `sensor.daily_ev_charging_cost`

### Alarm dashboard

The weekday alarm tile includes:

- `input_datetime.weekday_alarm`
- `input_boolean.weekday_alarm_on`
- `input_datetime.next_work_meeting`

`input_boolean.special_meeting` still exists for the workday alarm flow, but the Tesla planner does not use it.

## Validation

Recommended validation after planner changes:

```bash
yamllint -d "{extends: relaxed, rules: {line-length: disable, empty-lines: disable, truthy: disable}}" \
  configuration.yaml automations.yaml blueprints packages zigbee2mqtt

uv run --python 3.14.2 --with homeassistant==2026.3.3 \
  python -m homeassistant --config "$PWD" --script check_config
```
