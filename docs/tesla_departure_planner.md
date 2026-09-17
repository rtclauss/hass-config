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
- `input_number.tesla_local_trip_threshold_mi`

`binary_sensor.upcoming_trip_charging` is a **trigger-based** template sensor. On a schedule (HA start, every 15 minutes, and whenever `calendar.ryan_claussen`, `calendar.curling`, or `binary_sensor.work_trip_today` changes) it:

1. Fetches every event in the next 24 hours from `calendar.ryan_claussen` and `calendar.curling` via the `calendar.get_events` action (not each calendar entity's own single pinned "current event" attribute — see below), plus `binary_sensor.work_trip_today`'s own event.
2. Drops any event that is all-day, in the past, outside the 24-hour horizon, or a flight/`nocharge` event (via the shared `skip_charging_event` macro, unchanged).
3. Calls `waze_travel_time.get_travel_times` once per remaining candidate that has a location, scoring it with a real drive distance/duration from home.
4. Excludes any candidate closer than `input_number.tesla_local_trip_threshold_mi` (default 10 mi, adjustable on the dashboard) — a nearby errand is never treated as a "trip" worth preconditioning for.
5. Of what's left ("qualifying" candidates), the **soonest** one drives departure timing/preconditioning (`entry`, `start_time`, `duration_min`), and the **furthest** one drives the charge limit (`distance_mi`, `furthest_entry`). If your day has a nearby dentist visit at 10am and a 100 mi loan closing at 1pm, the car preconditions for the 10am departure but charges to whatever the 100 mi trip needs.

This replaced an older design that read each calendar entity's own single "current event" attribute (`state_attr(calendar, 'start_time'/'message')`). HA calendar entities only ever expose *one* such event, and while a same-day **all-day** event is active (for example a recurring "Replace Contacts" reminder) it pins that attribute for the entire day — so a real timed event later that day (a 10am dentist appointment) was invisible to the planner. All-day events are now excluded from candidacy outright, and the full event list is enumerated instead of trusting that single pinned attribute.

The planner now normalizes Waze duration with Home Assistant's `as_timedelta` helper where needed, so legacy numeric values still work.

If a Waze lookup fails for one candidate (`continue_on_error: true`), that candidate degrades to 0 mi/0 min rather than crashing the whole sensor recompute — the same as if it were a local trip. `sensor.waze_next_trip_distance` and `sensor.calendar_destination` still exist as passive display-only entities (the "Next Calendar Destination" dashboard tile mirrors `binary_sensor.upcoming_trip_charging`'s `location` attribute, falling back to home), but neither is read by the planning logic anymore.

The trip-selection template only considers future departures inside the next 24 hours. Once a calendar departure is in the past, its `start_time` drops out of the planner inputs and the next planner recompute clears Tesla scheduled departure instead of leaving stale preconditioning or off-peak charging events behind.

Flight events are excluded from charge planning entirely. Candidate-building runs every calendar event through the shared `skip_charging_event` macro in `custom_templates/flight.jinja`, which reuses the same flight-recognition rules as travel detection in `packages/trips.yaml` (route-arrow itineraries such as `✈ MSP→ATL`, `flight to …` / `flight: … to …` titles, and itinerary markers like "Synced by Flighty", "Created from an email you received in Gmail", booking codes, and flight-time lines). This is intentionally origin-agnostic: unlike trip-mode detection, the charge planner ignores a flight regardless of whether it departs MSP, because the car never makes the long drive to the arrival city. Previously a far-destination flight (for example "Flight to Atlanta") fed the Waze drive distance to the arrival city, tripped the `>= 90 mi -> 100%` rule, and pinned the home Tesla to a 100% charge. The same macro still honors the manual `nocharge` description tag as an explicit opt-out.

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

At `home`, Home Assistant always sets the charge limit. For a real calendar departure, it also schedules cabin preconditioning whenever both Ryan and Nigori are home, regardless of the selected charge target. The scheduled-departure command preserves the Tesla app's charging defaults by omitting off-peak charging fields at protected locations. Alarm-only plans still do not schedule cabin preconditioning.

`person.ryan` and `device_tracker.nigori_location_tracker` are both safety inputs. The planner will not create a preconditioning schedule unless both are `home`. If either leaves after Home Assistant creates a managed departure, `automation.tesla_departure_cancel_when_home_context_ends` disables that managed departure and clears its tracking helpers after Tesla confirms the matching schedule. If the integration has not published the new departure timestamp yet, the automation keeps the departure tracked and retries when `binary_sensor.nigori_scheduled_departure` catches up.

At `parents`, `OCC`, and `SPCC`, the planner is currently hands-off. Those locations are protected so Tesla-app charging defaults remain authoritative there, and Home Assistant does not actively create departure plans there.

### Manual override

- `input_boolean.long_range_travel`

This is the explicit max-range override surfaced on the Tesla dashboard.

When it is on, the planner pins the charge limit to `100%`.

## Outputs

### Charge limit

- `number.nigori_charge_limit`

Decision summary (`distance_mi` below is always the **furthest** qualifying event in the next 24 hours, not necessarily the next one to depart):

- inside the local trip threshold (`< input_number.tesla_local_trip_threshold_mi`, default 10 mi): not a trip at all — falls through to the alarm/no-plan tiers below
- long trip (`>= 90 mi`): `100%`
- other qualifying trip (`>= threshold` and `< 90 mi`): `90%`
- alarm + cold weather: `90%`
- alarm + lower EV tariff: `85%`
- alarm + higher EV tariff: `80%`
- no plan: `80%`
- manual max-range override: `100%`

### Scheduled departure

Script:

- `script.tesla_set_precondition_schedule_time`

Behavior:

- enables Tesla scheduled departure for real calendar departures with a valid future departure time whenever both Ryan and Nigori are home, regardless of charge target
- does not enable Tesla scheduled departure for alarm-only plans; those only influence charge-limit planning and planner messaging
- disables Tesla scheduled departure when the planner no longer has a Home Assistant-managed preconditioning plan to keep
- refuses to schedule preconditioning when the computed departure window is already in the past
- stores the last Home Assistant-managed Tesla departure as a Unix timestamp in `input_number.tesla_managed_departure_ts` and tracks whether that schedule is active with `input_boolean.tesla_managed_departure_active`
- clears that Home Assistant-managed Tesla schedule as soon as the stored departure time passes, even if the car is no longer at home
- skips scheduled departure for all-day calendar events
- preserves Tesla-app charging schedules at `home` while scheduling cabin preconditioning separately
- requests cancellation of a Home Assistant-managed departure immediately if either Ryan or Nigori leaves home
- retries that away-state cancellation when Tesla publishes a delayed scheduled-departure timestamp, while retaining the live-schedule match guard that protects Tesla-app schedules
- preserves Tesla-app charging schedules at protected locations during cleanup by only clearing Tesla when the live scheduled-departure state still matches the stored HA-managed departure and Tesla is not advertising scheduled charging or off-peak charging

### Notifications

The planner sends Tesla status notifications with a deep link to the storage dashboard Tesla view:

- `/ryan-new-mushroom/tesla-v2`

Notifications fire on: the nightly 21:35 digest (if a plan is active), `binary_sensor.upcoming_trip_charging` transitioning off → on while `tesla_plan.active` is true (a new qualifying trip appears), and the 04:30 early-morning check when preconditioning is active with low tire pressure. The reverse on → off transition does **not** notify on its own — once the trip sensor turns off there is usually no active plan left to report (`tesla_plan.active` also depends on `has_calendar_departure`, which goes false at the same time), so a deactivation only notifies in the separate case where a weekday/weekend alarm or the manual max-range override keeps `tesla_plan.active` true regardless.

The `trip_change` trigger itself has no attribute filter — it exists so the automation recomputes on every sensor update — but the notify condition only fires it when `trigger.from_state.state` and `trigger.to_state.state` are both a real `on`/`off` value and differ from each other. Without that guard, `distance_mi`/`duration_min` drifting a little with live Waze traffic on every 15-minute recompute (while a trip stays active for hours, e.g. overnight) would re-notify on every tick instead of once when the plan actually changed. Requiring both sides to be `on`/`off` specifically (not just "different") also keeps a transient `unavailable`/`unknown` blip — an HA restart or template reload recovering straight back to `on` — from reading as a fresh activation.

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
- A same-day all-day event (for example a recurring "Replace Contacts" reminder) never becomes the planner's selected `entry`/`start_time`, even while it is the only event calendar.ryan_claussen's own native attributes would otherwise expose; a real timed event later that day (for example a 10am dentist appointment) is still picked up via `calendar.get_events`.
- With three same-day qualifying events — two inside the local trip threshold and one 100 mi away — the charge limit reflects the 100 mi trip (`distance_mi` = furthest), while `entry`/`start_time`/preconditioning still follow whichever qualifying event departs soonest.
- Raising or lowering `input_number.tesla_local_trip_threshold_mi` changes which events count as a "trip" at all; an event just inside the radius produces no plan, and the same event just outside it produces one.
- If the Waze lookup for one candidate's location fails, that candidate scores 0 mi/0 min (treated like a local trip) instead of leaving a stale distance from a previous recompute or erroring the whole sensor.
- At `home`, a real calendar departure schedules cabin preconditioning at `80%`, `90%`, or `100%` without changing Tesla-app charging defaults.
- Alarm-only plans adjust charge limit and planner messaging but do not create Tesla scheduled departure or cabin-preconditioning overrides.
- When either `person.ryan` or `device_tracker.nigori_location_tracker` leaves `home`, any active Home Assistant-managed departure is disabled and its tracking helpers are cleared.
- At `parents`, `OCC`, and `SPCC`, Tesla dashboard text reflects that Home Assistant is preserving Tesla-app defaults and not actively planning departures there.
- When there is no active stored `input_number.tesla_managed_departure_ts`, the planner does not send a redundant Tesla disable call.
- At protected locations, cleanup/no-plan disables only call the Tesla API when the live Tesla scheduled-departure state still matches the stored HA-managed departure and Tesla is not advertising scheduled charging or off-peak charging.
