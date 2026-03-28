# Tesla Departure Planner

This document describes the Tesla departure planner added in `packages/car.yaml`.

## Purpose

The planner sets the Tesla charge limit and scheduled departure behavior based on:

- upcoming trips
- upcoming calendar departures
- weekday/weekend alarm settings
- weather
- EV charging tariff/rate
- vehicle location
- a manual max-range override

## Inputs

### Trip inputs

- `binary_sensor.upcoming_trip_charging`
- `sensor.waze_next_trip_distance`

If an upcoming calendar departure exists, the planner uses trip start time plus Waze duration to determine a departure window.

The `binary_sensor.upcoming_trip_charging` state still represents the longer-distance charging case. The planner also uses that sensor's `start_time` attribute for shorter calendar departures that should precondition but do not need a higher charge limit.

The planner now normalizes Waze/Tesla duration inputs with Home Assistant's `as_timedelta` helper, so legacy numeric values still work and string durations such as `00:35:00` or `PT35M` are accepted as well.

The trip-selection template now only considers future departures inside the next 24 hours. Once a calendar departure is in the past, its `start_time` drops out of the planner inputs and the next planner recompute clears Tesla scheduled departure instead of leaving stale preconditioning or off-peak charging events behind.

### Alarm inputs

- `input_boolean.weekday_alarm_on`
- `input_boolean.weekend_alarm_on`
- `input_datetime.weekday_alarm`
- `input_datetime.weekend_alarm`

These drive non-trip next-morning departure planning.

Alarm-only plans affect charge-limit planning, but they do not create Tesla scheduled-departure or cabin-preconditioning overrides on their own. Cabin preconditioning only runs when there is a real upcoming calendar departure.

### Weather inputs

- `sensor.outside_temperature`

Cold weather currently means `<= 20F`.

Cold weather increases departure buffer time and can justify a higher charge target.

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

### Location input

- `device_tracker.nigori_location_tracker`

The schedule helper preserves the Tesla app's own charging schedule when the car is at:

- `home`
- `parents`
- `OCC`
- `SPCC`

At `home`, Home Assistant always sets the charge limit, but it only pushes a Tesla scheduled-departure override when the planner needs a non-default home charge target. Default-`80%` alarm or calendar plans keep the Tesla app's own home charging schedule authoritative and do not create extra Tesla schedule entries.

At `parents`, `OCC`, and `SPCC`, the planner is currently hands-off. Those locations are protected so Tesla-app charging defaults remain authoritative there, and Home Assistant does not actively create departure plans there.

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
- shorter calendar departure: keep the default `80%`
- alarm + cold weather: `90%`
- alarm + lower EV tariff: `85%`
- alarm + higher EV tariff: `80%`
- no plan: `80%`
- manual max-range override: `100%`

### Scheduled departure

Script:

- `script.tesla_set_precondition_schedule_time`

Behavior:

- enables Tesla scheduled departure only for real calendar departures that still have a valid future departure time and need a Home Assistant-managed override
- does not enable Tesla scheduled departure for alarm-only plans; those only influence charge-limit planning and planner messaging
- disables Tesla scheduled departure when the planner no longer has a Home Assistant-managed preconditioning plan to keep
- refuses to schedule preconditioning when the computed departure window is already in the past
- stores the last Home Assistant-managed Tesla departure in `input_text.tesla_managed_departure_time`
- clears that Home Assistant-managed Tesla schedule as soon as the stored departure time passes, even if the car is no longer at home
- skips scheduled departure for all-day calendar events
- preserves Tesla-app charging schedules at `home` unless the planner needs a non-default home charge target
- skips Tesla scheduled-departure writes for protected-location default-`80%` plans so preconditioning-only home plans do not create extra Tesla schedule entries
- preserves Tesla-app charging schedules at protected locations during cleanup by only clearing Tesla when the live scheduled-departure state still matches the stored HA-managed departure and Tesla is not advertising scheduled charging or off-peak charging

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

Manual regression cases worth checking in Template Developer Tools or against live entities:

- Waze `duration` as a numeric minute count still produces the same planned departure.
- Waze `duration` as `HH:MM:SS` or ISO8601 (for example `PT42M`) still produces the same planned departure.
- Tesla `sensor.nigori_charging_rate` `time_left` as fractional hours still produces a valid `charge_complete` timestamp.
- Tesla `sensor.nigori_charging_rate` `time_left` as `HH:MM:SS` or ISO8601 still produces a valid `charge_complete` timestamp.
- A just-finished calendar departure disappears from `binary_sensor.upcoming_trip_charging` and clears Tesla scheduled departure on the next planner recompute.
- A calendar event that is still upcoming but already inside the departure buffer skips scheduled preconditioning instead of creating a stale past-due Tesla schedule.
- At `home`, default-`80%` alarm or calendar departures do not create extra Tesla schedule entries, while non-default charge targets can still create a temporary Home Assistant-managed override.
- Alarm-only plans adjust charge limit and planner messaging but do not create Tesla scheduled departure or cabin-preconditioning overrides.
- At `home`, a real calendar departure can still create or update Tesla scheduled departure/preconditioning when the planner needs a non-default charge target, while default-`80%` home plans leave the Tesla app schedule in place.
- At `parents`, `OCC`, and `SPCC`, Tesla dashboard text reflects that Home Assistant is preserving Tesla-app defaults and not actively planning departures there.
- When there is no stored `input_text.tesla_managed_departure_time`, the planner does not send a redundant Tesla disable call.
- At protected locations, cleanup/no-plan disables only call the Tesla API when the live Tesla scheduled-departure state still matches the stored HA-managed departure and Tesla is not advertising scheduled charging or off-peak charging.
