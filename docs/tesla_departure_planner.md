# Tesla Departure Planner

This document describes the Tesla departure planner added in `packages/car.yaml`.

## Purpose

The planner sets the Tesla charge limit and scheduled departure behavior based on:

- upcoming trips
- weekday/weekend alarm settings
- weather
- electricity tariff/rate
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

### `special_meeting`

`special_meeting` is a UI helper, not a calendar entity.

- Entity: `input_boolean.special_meeting`
- Defined in `packages/workday.yaml`
- Exposed in the weekday alarm UI tile at `lovelace/tiles/tiles_weekday_alarm.yaml`

When `special_meeting` is on, the planner treats the next alarm like a higher-priority morning:

- adds extra prep time before departure
- allows a higher charge target
- enables preconditioning even if the weather is not cold

The workday alarm flow also uses it as a dedicated `meeting-alarm` path and turns it back off after that alarm runs.

### Weather inputs

- `sensor.outside_temperature`

Cold weather currently means `<= 20F`.

Cold weather increases departure buffer time and can justify preconditioning or a higher charge target.

### Tariff inputs

- `select.daily_electricity`
- `select.hourly_electricity`
- `input_number.electrical_rate`

The planner treats the tariff as "higher" when:

- the tariff name includes `summer`
- the tariff name is `peak`, `on-peak`, or `onpeak`
- the numeric electrical rate is `>= 0.13`

This only affects the non-trip alarm top-off case. Trip charging and cold-weather/special-meeting cases still take priority.

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
- alarm + cold weather or `special_meeting`: `90%`
- alarm + lower tariff: `85%`
- alarm + higher tariff: `80%`
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

Controls:

- `Max Range Override`
- `Use Daily Plan`

### Alarm dashboard

The weekday alarm tile includes:

- `input_datetime.weekday_alarm`
- `input_boolean.weekday_alarm_on`
- `input_datetime.next_work_meeting`
- `input_boolean.special_meeting`

## Validation

Recommended validation after planner changes:

```bash
yamllint -d "{extends: relaxed, rules: {line-length: disable, empty-lines: disable, truthy: disable}}" \
  configuration.yaml automations.yaml blueprints packages zigbee2mqtt

uv run --python 3.14.2 --with homeassistant==2026.3.3 \
  python -m homeassistant --config "$PWD" --script check_config
```
