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
- `input_number.tesla_degraded_travel_min`
- `input_number.tesla_usable_range_mi` (reporting only; never changes the charge target)
- `input_text.tesla_destination_coords_override`

`binary_sensor.upcoming_trip_charging` is a **trigger-based** template sensor. On a schedule (HA start, every 15 minutes, and whenever `calendar.<private_owner_calendar>`, `calendar.curling`, or `binary_sensor.work_trip_today` changes) it:

1. Fetches every event in the next 24 hours from `calendar.<private_owner_calendar>` and `calendar.curling` via the `calendar.get_events` action (not each calendar entity's own single pinned "current event" attribute — see below), plus `binary_sensor.work_trip_today`'s own event.
2. Drops any event that is all-day, in the past, outside the 24-hour horizon, or a flight/`nocharge` event (via the shared `skip_charging_event` macro, unchanged).
3. Resolves each remaining candidate's `location` to a `lat,lon` pair (see [Coordinates, not addresses](#coordinates-not-addresses) below), then calls `waze_travel_time.get_travel_times` once per candidate, scoring it with a real drive distance/duration from home.
4. Excludes any candidate closer than `input_number.tesla_local_trip_threshold_mi` (default 10 mi, adjustable on the dashboard) — a nearby errand is never treated as a "trip" worth preconditioning for.
5. Of what's left ("qualifying" candidates), the **soonest** one drives departure timing/preconditioning (`entry`, `start_time`, `duration_min`), and the **furthest** one drives the charge limit (`distance_mi`, `furthest_entry`). If your day has a nearby dentist visit at 10am and a 100 mi loan closing at 1pm, the car preconditions for the 10am departure but charges to whatever the 100 mi trip needs.

This replaced an older design that read each calendar entity's own single "current event" attribute (`state_attr(calendar, 'start_time'/'message')`). HA calendar entities only ever expose *one* such event, and while a same-day **all-day** event is active (for example a recurring "Replace Contacts" reminder) it pins that attribute for the entire day — so a real timed event later that day (a 10am dentist appointment) was invisible to the planner. All-day events are now excluded from candidacy outright, and the full event list is enumerated instead of trusting that single pinned attribute.

The planner now normalizes Waze duration with Home Assistant's `as_timedelta` helper where needed, so legacy numeric values still work.

`sensor.waze_next_trip_distance` and `sensor.calendar_destination` still exist as passive display-only entities (the "Next Calendar Destination" dashboard tile mirrors `binary_sensor.upcoming_trip_charging`'s `location` attribute, falling back to home), but neither is read by the planning logic anymore.

### Coordinates, not addresses

Waze routes reliably by coordinate, but in November 2026 Waze blocked the address-autocomplete endpoint `pywaze` used to turn an address string into coordinates ([eifinger/pywaze#119](https://github.com/eifinger/pywaze/issues/119), core [#191329](https://github.com/home-assistant/core/issues/191329) / [#191667](https://github.com/home-assistant/core/issues/191667)). `waze_travel_time.get_travel_times` now fails for *any* address input, so the planner passes coordinates on both sides:

- **Origin** comes from `zone.home`'s own `latitude`/`longitude`. It never needs geocoding.
- **Destination** is geocoded from the calendar event's `location` via `rest_command.geocode_address` (Nominatim, `format=jsonv2&limit=1`) with a contactable `User-Agent`, as Nominatim's usage policy requires. The error case is a JSON *mapping* and a no-match is an empty list, so the parser requires a non-mapping, non-empty sequence before indexing the first result.
- Resolved coordinates are cached in `binary_sensor.upcoming_trip_charging`'s own `geo_cache` attribute and carried forward across recomputes, so the same event is not re-geocoded every 15 minutes. The cache is pruned each cycle to the addresses still in the 24-hour window.
- `input_text.tesla_destination_coords_override` is the manual escape hatch. Set it to `lat,lon` and it wins outright for the **soonest candidate that has a location** — deliberately scoped that way so one entry stays unambiguous when several located events share the window. An override is **never written into `geo_cache`**, so clearing or correcting it restores real geocoding on the next recompute instead of leaving a stale pin that a later event at the same address would inherit.

Coordinates are carried **inside mappings** (`planner_home_coords.pair`, `candidate_coords.pair`) and the Waze call renders its whole `data:` block as a single template, rather than passing bare `"{{ … }}"` scalars. Home Assistant renders script variables and service data with native typing, and a bare `lat,lon` string `literal_eval`s into a **tuple** — verified on the live instance over the WebSocket `render_template` API, which returns `[40.001, -80.001]` for the bare form while the same value inside a rendered mapping stays a string. A `| string` filter does not save it, because the parse happens *after* rendering. `waze_travel_time`'s service schema uses `TextSelector`, which strictly validates `str`, and a config-validation error bypasses `continue_on_error` — so a bare coordinate pair aborts the whole action before the degraded fallback can be produced. Street addresses never had this problem because they do not `literal_eval`, which is why it only surfaced once the planner moved to coordinates.

This is also why `sensor.me_to_home` kept working throughout the outage: it is configured with a coordinate pair and never geocodes anything.

### When a travel time cannot be scored

A candidate that *has* a location but whose coordinates or Waze route could not be resolved is **not** scored as 0 mi. Scoring 0 was a fail-open bug: 0 is below the local-trip threshold, so a lost lookup silently reclassified a real long drive as a nearby errand, dropped it from candidacy, and cancelled preconditioning — leaving a plausible-looking alarm-tier charge limit as the only symptom (see the linked tracking issue).

Instead such a candidate carries `scored: false` and:

- still **qualifies** as a trip, bypassing the local-trip threshold, so preconditioning survives a geocoder or Waze outage
- contributes 0 to the furthest-distance calculation, which keeps it in the conservative sub-90-mile `90%` tier rather than letting an unknown distance pin the car to `100%`
- times departure off `input_number.tesla_degraded_travel_min` (default 60 min, calibrate from real drives) instead of an unknown 0-minute drive, so preconditioning starts early rather than after the real departure
- sets `scoring_degraded` on the sensor, which the planner summary and notifications state explicitly — a degraded plan never passes as a normal one

An event with **no** location is unchanged: it tells the planner nothing, stays a non-trip, and never starts preconditioning.

The trip-selection template only considers future departures inside the next 24 hours. Once a calendar departure is in the past, its `start_time` drops out of the planner inputs and the next planner recompute clears Tesla scheduled departure instead of leaving stale preconditioning or off-peak charging events behind.

Flight events are excluded from charge planning entirely. Candidate-building runs every calendar event through the shared `skip_charging_event` macro in `custom_templates/flight.jinja`, which reuses the same flight-recognition rules as travel detection in `packages/trips.yaml` (route-arrow itineraries such as `✈ AAA→BBB`, `flight to …` / `flight: … to …` titles, and itinerary markers like "Synced by Flighty", "Created from an email you received in Gmail", booking codes, and flight-time lines). This is intentionally origin-agnostic: unlike trip-mode detection, the charge planner ignores a flight regardless of whether it departs a home airport, because the car never makes the long drive to the arrival city. Previously a far-destination flight (for example "Flight to Sample City") fed the Waze drive distance to the arrival city, tripped the `>= 90 mi -> 100%` rule, and pinned the home Tesla to a 100% charge. The same macro still honors the manual `nocharge` description tag as an explicit opt-out.

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

- `device_tracker.<private_vehicle_tracker>`

The schedule helper preserves the Tesla app's own charging schedule when the car is at:

- `home`
- `parents`
- `OCC`
- `SPCC`

At `home`, Home Assistant always sets the charge limit. For a real calendar departure, it also schedules cabin preconditioning whenever both the resident and the vehicle are home, regardless of the selected charge target. At protected locations the command preserves the Tesla app's charging defaults by **echoing the vehicle's own current off-peak settings back**, not by omitting those fields — see [Scheduled departure needs all seven parameters](#scheduled-departure-needs-all-seven-parameters). Alarm-only plans still do not schedule cabin preconditioning.

### Scheduled departure needs all seven parameters

Tesla's `set_scheduled_departure` command requires **every** one of these, and rejects the whole command if any is absent:

```
enable  departure_time  preconditioning_enabled  preconditioning_weekdays_only
off_peak_charging_enabled  off_peak_charging_weekdays_only  end_off_peak_time
```

A partial payload comes back as `{"result": false, "reason": "missing <name> param"}`, naming each absent field in turn. `teslajsonpy` maps the command to `POST api/1/vehicles/{vehicle_id}/command/set_scheduled_departure` and passes `**kwargs` straight through as the request body with no validation and no defaults, so an omitted field reaches Tesla genuinely missing.

This is why preconditioning silently never armed at `home` until issue #1200: that path omitted all three off-peak fields to avoid disturbing the Tesla-app charging schedule, so the command was rejected every time. The fix sends the vehicle's own current values (`Off peak charging enabled`, `Off peak charging weekdays only`, `End off peak time`, read back from `binary_sensor.<vehicle_slug>_scheduled_departure`), which preserves those settings while satisfying the contract. `End off peak time` is `None` when off-peak charging has never been configured; `0` is accepted.

`tesla_custom.api` is registered with `supports_response=True` and returns Tesla's answer. The planner now **captures** it on both enable paths and fails closed: an empty or absent response counts as failure, the reason reaches the logbook and a persistent notification (`tesla_departure_arm_failed`), and the script stops with an error so `input_number.tesla_managed_departure_ts` and `input_boolean.tesla_managed_departure_active` are never written for a schedule the car did not accept. Previously the response was discarded and HA recorded a managed departure regardless, so the only symptom was a `binary_sensor.<vehicle_slug>_scheduled_departure` that never turned on.

`person.<resident>` and `device_tracker.<private_vehicle_tracker>` are both safety inputs. The planner will not create a preconditioning schedule unless both are `home`. If either leaves after Home Assistant creates a managed departure, `automation.tesla_departure_cancel_when_home_context_ends` disables that managed departure and clears its tracking helpers after Tesla confirms the matching schedule. If the integration has not published the new departure timestamp yet, the automation keeps the departure tracked and retries when `binary_sensor.<vehicle_slug>_scheduled_departure` catches up.

At `parents`, `OCC`, and `SPCC`, the planner is currently hands-off. Those locations are protected so Tesla-app charging defaults remain authoritative there, and Home Assistant does not actively create departure plans there.

### Manual override

- `input_boolean.long_range_travel`

This is the explicit max-range override surfaced on the Tesla dashboard.

When it is on, the planner pins the charge limit to `100%`.

## Outputs

### Charge limit

- `number.<vehicle_slug>_charge_limit`

Decision summary (`distance_mi` below is always the **furthest** qualifying event in the next 24 hours, not necessarily the next one to depart):

> **These thresholds are one-way figures acting as round-trip proxies.** The car's charger is at home, so every out-leg implies a return leg. Read the table as: `>= 90 mi` one-way is a **~180 mi round trip**, and the `>= threshold and < 90 mi` band covers round trips up to ~180 mi. A 70 mi one-way appointment is **~140 mi of driving**, not 70. Mistaking these for one-way-only numbers makes the tiers look far more conservative than they are.

- inside the local trip threshold (`< input_number.tesla_local_trip_threshold_mi`, default 10 mi): not a trip at all — falls through to the alarm/no-plan tiers below
- qualifying trip whose travel time could not be scored: `90%` (distance contributes 0, so it never reaches the `>= 90 mi` tier), with `scoring_degraded` set
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

- enables Tesla scheduled departure for real calendar departures with a valid future departure time whenever both the resident and the vehicle are home, regardless of charge target
- does not enable Tesla scheduled departure for alarm-only plans; those only influence charge-limit planning and planner messaging
- disables Tesla scheduled departure when the planner no longer has a Home Assistant-managed preconditioning plan to keep
- refuses to schedule preconditioning when the computed departure window is already in the past
- stores the last Home Assistant-managed Tesla departure as a Unix timestamp in `input_number.tesla_managed_departure_ts` and tracks whether that schedule is active with `input_boolean.tesla_managed_departure_active`
- clears that Home Assistant-managed Tesla schedule as soon as the stored departure time passes, even if the car is no longer at home
- skips scheduled departure for all-day calendar events
- preserves Tesla-app charging schedules at `home` while scheduling cabin preconditioning separately
- requests cancellation of a Home Assistant-managed departure immediately if either the resident or the vehicle leaves home
- retries that away-state cancellation when Tesla publishes a delayed scheduled-departure timestamp, while retaining the live-schedule match guard that protects Tesla-app schedules
- preserves Tesla-app charging schedules at protected locations during cleanup by only clearing Tesla when the live scheduled-departure state still matches the stored HA-managed departure and Tesla is not advertising scheduled charging or off-peak charging

### Day total, and why the charge target is never inflated for it

The charge tier is sized off the **furthest** qualifying event. On a day with several qualifying trips the other legs would otherwise be invisible, so the plan also reports the whole day:

- `binary_sensor.upcoming_trip_charging` carries `day_round_trip_mi` (every qualifying event counted as a **round trip**) and `trip_count`
- the summary and notification add a line such as *"Day total 175 mi across 2 trips (round trip each)"*
- if that total exceeds what the selected tier provides, one advisory sentence is appended naming the shortfall

An illustrative shape: a 70 mi afternoon appointment plus a 17 mi evening event is **~174 mi of driving**, while the plan's `distance_mi` reads 70 — correctly, since that is the leg that sizes the charge. Without the day total, nothing in the plan hints at the other 104 mi.

**The day total never changes the charge limit.** That is deliberate (issue #1202):

- Supercharging is available on these routes, so under-charging costs a short stop and a worse rate, not a missed appointment
- the pack is a 2019 Model 3 NCA, where routine 100% charging is the pattern to avoid and 90% is the daily ceiling
- so over-charging carries a real cumulative cost and under-charging a small recoverable one — the planner informs and leaves the decision to the owner, who can Supercharge or flip `input_boolean.long_range_travel`

The comparison uses `input_number.tesla_usable_range_mi` (rated miles at 100%, default 240). It is a **fixed, calibrated** figure, not a live reading — recalibrate it from an observed full charge if it drifts. It is only ever used to phrase the advisory.

Two honesty details. When `scoring_degraded` is set, an unscored trip is counted in `trip_count` but contributes no miles, so the wording becomes *"Day total at least N mi"* rather than understating the driving. And the total sums **all** qualifying events rather than only those too close together to recharge between — pessimistic by design, since the car usually does charge at home between trips. That approximation is acceptable because the figure is reported, never acted on.

A dependency worth knowing: whether the car recovers charge between trips depends on `Off peak charging enabled` on the vehicle. It is currently `False`, so the car charges on arrival instead of waiting for the 21:00 off-peak window — which is what makes a two-trip day like the example comfortable (home ~16:40, leave again ~20:10). If off-peak-only charging were ever enabled, that recovery window closes and **nothing in the planner would notice**.

For context on how unusual this is: no surveyed project computes a required charge level from trip distance at all. EV Smart Charging optimises electricity price against a target SOC percentage; Teslemetry and Tesla Fleet hand a departure time to the car and let it plan. None of them models round trips, multi-trip days, or a cold-weather derate. See the research notes on issue #1202.

### Notifications

The planner sends Tesla status notifications with a deep link to the storage dashboard Tesla view:

- `/<private_dashboard>/tesla-v2`

Notifications fire on: the nightly 21:35 digest (if a plan is active), `binary_sensor.upcoming_trip_charging` transitioning off → on while `tesla_plan.active` is true (a new qualifying trip appears), and the 04:30 early-morning check when preconditioning is active with low tire pressure. The reverse on → off transition does **not** notify on its own — once the trip sensor turns off there is usually no active plan left to report (`tesla_plan.active` also depends on `has_calendar_departure`, which goes false at the same time), so a deactivation only notifies in the separate case where a weekday/weekend alarm or the manual max-range override keeps `tesla_plan.active` true regardless.

The `trip_change` trigger itself has no attribute filter — it exists so the automation recomputes on every sensor update — but the notify condition only fires it when `trigger.from_state.state` and `trigger.to_state.state` are both a real `on`/`off` value and differ from each other. Without that guard, `distance_mi`/`duration_min` drifting a little with live Waze traffic on every 15-minute recompute (while a trip stays active for hours, e.g. overnight) would re-notify on every tick instead of once when the plan actually changed. Requiring both sides to be `on`/`off` specifically (not just "different") also keeps a transient `unavailable`/`unknown` blip — an HA restart or template reload recovering straight back to `on` — from reading as a fresh activation.

## UI locations

### Tesla dashboard

Storage-mode dashboard:

- the private UI-owned Lovelace dashboard in `.storage/`
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
- Tesla `sensor.<vehicle_slug>_charging_rate` `time_left` as fractional hours still produces a valid `charge_complete` timestamp.
- Tesla `sensor.<vehicle_slug>_charging_rate` `time_left` as `HH:MM:SS` or ISO8601 still produces a valid `charge_complete` timestamp.
- A just-finished calendar departure disappears from `binary_sensor.upcoming_trip_charging` and clears Tesla scheduled departure on the next planner recompute.
- A calendar event that is still upcoming but already inside the departure buffer skips scheduled preconditioning instead of creating a stale past-due Tesla schedule.
- A same-day all-day event (for example a recurring "Replace Contacts" reminder) never becomes the planner's selected `entry`/`start_time`, even while it is the only event calendar.<private_owner_calendar>'s own native attributes would otherwise expose; a real timed event later that day (for example a 10am dentist appointment) is still picked up via `calendar.get_events`.
- With three same-day qualifying events — two inside the local trip threshold and one 100 mi away — the charge limit reflects the 100 mi trip (`distance_mi` = furthest), while `entry`/`start_time`/preconditioning still follow whichever qualifying event departs soonest.
- Raising or lowering `input_number.tesla_local_trip_threshold_mi` changes which events count as a "trip" at all; an event just inside the radius produces no plan, and the same event just outside it produces one. A candidate that could not be scored bypasses this threshold on purpose.
- A `waze_travel_time.get_travel_times` call with a coordinate pair succeeds while the same call with a street address fails — the upstream block this design works around. Verify with a direct action call in Developer Tools.
- A located candidate whose geocode returns a Nominatim error mapping, an empty list, or nothing at all still produces an active plan at `90%` with `scoring_degraded` true and departure timed off `input_number.tesla_degraded_travel_min` — not a dropped candidate and not a `100%` pin.
- An event with no `location` still produces no plan even while geocoding is failing for everything else.
- Setting `input_text.tesla_destination_coords_override` to `lat,lon` overrides the soonest located candidate's destination; with two located events, the later one is unaffected.
- Repeated 15-minute recomputes of the same unchanged event hit `rest_command.geocode_address` once, not once per cycle (check `geo_cache` on the sensor).
- If the Waze lookup for one candidate's location fails, that candidate scores 0 mi/0 min (treated like a local trip) instead of leaving a stale distance from a previous recompute or erroring the whole sensor.
- At `home`, a real calendar departure schedules cabin preconditioning at `80%`, `90%`, or `100%` without changing Tesla-app charging defaults.
- Alarm-only plans adjust charge limit and planner messaging but do not create Tesla scheduled departure or cabin-preconditioning overrides.
- When either `person.<resident>` or `device_tracker.<private_vehicle_tracker>` leaves `home`, any active Home Assistant-managed departure is disabled and its tracking helpers are cleared.
- At `parents`, `OCC`, and `SPCC`, Tesla dashboard text reflects that Home Assistant is preserving Tesla-app defaults and not actively planning departures there.
- When there is no active stored `input_number.tesla_managed_departure_ts`, the planner does not send a redundant Tesla disable call.
- At protected locations, cleanup/no-plan disables only call the Tesla API when the live Tesla scheduled-departure state still matches the stored HA-managed departure and Tesla is not advertising scheduled charging or off-peak charging.
