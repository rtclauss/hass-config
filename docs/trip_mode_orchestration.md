# Trip Mode Orchestration

Issue: `#118`

## Summary

Trip mode is the travel umbrella state for long absences. The canonical state is
`input_boolean.trip`; all automated trip enable/disable paths should route
through `automation.trip_mode_manager` so vacation simulation and cleanup stay
deterministic.

## State Ownership

`automation.trip_mode_manager` owns writes to `input_boolean.trip` for automated
travel decisions and reconciliation events. Other automations that need to
resolve trip mode should emit `trip_mode_resolution_requested` with:

- `desired_state`: `on` or `off`
- `reason`: a concise source such as `startup_reconcile` or
  `watchdog_home_1h`

The manager then calls `script.house_transition` with `apply_trip_policy: true`.
That keeps `switch.vacation_simulation` and
`input_number.random_vacation_light_group` in sync with the trip state.

## Current Inputs

- Manual toggle: `input_boolean.trip`
- Presence: `binary_sensor.bayesian_occupant_home`
- Distance threshold: `input_number.trip_trigger_radius_miles`
- Calendar sensors: `binary_sensor.planned_vacation_calendar`,
  `binary_sensor.planned_work_trip_calendar`, and
  `sensor.ecobee_calendar_vacation_schedule`
- Flight/calendar trigger: `calendar.resident_example`
- Reconciliation events: `trip_mode_resolution_requested`

## Side Effects

- Trip enable starts vacation simulation through `script.house_transition`.
- Trip disable stops vacation simulation and resets the random vacation light
  group through `script.house_transition`.
- Away lighting remains in `vacation_lights_on` and `vacation_lights_off`.
- Travel vacuuming remains in `vacuum_on_trip` (daily, 13:00) and `vacuum_flying_home`
  (the pre-landing clean, see below).
- Ecobee vacation windows remain in `sync_ecobee_calendar_vacation`.

## Guest And House-Sitter Policy

Guest mode is the current privacy-preserving house-sitter signal. Trip vacuuming
is suppressed when `input_boolean.guest_mode` is on and also requires the exact
`input_select.vacuum_pet_policy` state `Unattended`, matching
`docs/room_intent.yaml` guidance that automatic vacuuming should not intrude on
guest-capable rooms or bypass the cat-safe cleaning policy. Under `Unattended`,
the main floor is cleaned as two passes — a full vacuum, then a mop — with the
mop running when it is due (a mop is pending or the last mop is at least three
days old); flying home additionally forces the mop so we arrive to a mopped
floor. Only the main-floor X40 mops; the upstairs and den robots are vacuum-only.
Trip-mode vacation simulation is still allowed because it is an exterior/common-
area presence signal and is idempotently controlled by `script.house_transition`.

## Flying Home: Clean Finishes Before You Land

`vacuum_flying_home` is anchored to the flight's **landing**, not takeoff, and must be
**finished** `input_number.pre_arrival_clean_buffer_minutes` (default 30) before it:
`start = landing - input_number.pre_arrival_clean_lead_minutes` (default 240) and
`sensor.pre_arrival_clean_finish_by = landing - buffer`.

- `sensor.next_flight_home_arrival` is the `end_time` of the next not-yet-landed
  itinerary in `binary_sensor.flight_to_<private_home_airport_primary_code>_today` / `flight_to_<private_home_airport_secondary_code>_today` (those keep
  exposing the next flight in their attributes while off), so it is known days ahead.
- `sensor.pre_arrival_clean_start` = arrival minus the lead. The automation uses a
  `time` trigger on that sensor, plus catch-up triggers when it changes and on HA start.
- **Why 240 min:** 90 days of recorder history (2026-08-01..10-29) for all three robots.
  The X40 is the critical path: its two-pass vacuum+mop cycle measured 175-191 min
  (vacuum 78-90, mop 97-104; one cloud dropout stretched a vacuum pass to 109). The
  upstairs (<=72 min) and den (<=30 min) robots run in parallel and finish well inside it.
  240 = worst cycle 191 + the 30 min buffer + ~19 min margin. It is a fixed, reviewed
  number rather than one recomputed live: `vacuum.*` is excluded from the recorder, so
  durations must be reconstructed from status sensors, where back-to-back jobs (the
  13:00 litter pass), stacked queues and cloud dropouts blur the boundaries; a live
  estimator would absorb those errors silently. Re-measure and change the helper instead.
  Starting at takeoff (the original design) finished the 2026-10-09 clean 49 min after
  landing. The house is empty for the whole trip, so starting before takeoff is fine.
- **Late start** (itinerary added late, HA restart, schedule change): time left is
  measured to the finish-by deadline. With at least 195 min left it still runs the full
  cycle; with at least 100 min left it runs **vacuum-only** (`allow_mop: false`); with
  less it only notifies. Queued requests expire at the finish-by deadline. It launches
  once per landing (`input_datetime.pre_arrival_clean_done_for`, tolerant of a delay that
  moves the landing by under 6 h).
- **Upstairs and den are confirmed.** Their starts are fire-and-forget (an MQTT publish,
  and a den start its own guards may veto), and on 2026-10-26 neither ran.
  `script.pre_arrival_confirm_secondary_robots` gives each 3 min to show it is cleaning,
  re-sends one start through the same guarded scripts, then notifies which robot did not
  start and why (for example, den doors not confirmed closed).
- **One recovery retry** (`vacuum_flying_home_recover`). On 2026-10-26 the X40 dropped off
  the Dreame cloud mid-vacuum and its `task_status` reached `completed` 3 s after the dock
  was seen, so the vacuum pass was not credited and the mop never ran. The X40 passes now
  wait up to 2 min for `completed` (never crediting a run docked by an arrival or
  dock-all) and record `input_datetime.x40_ultra_last_vacuumed_at`. When the dispatcher
  goes idle, or after an HA restart (which docks every robot), the recover automation
  checks what finished since the clean started: no vacuum -> full cycle or vacuum-only,
  whichever still fits before the finish-by deadline; vacuumed but the owed mop missing ->
  a mop-only pass (`kind: mop_only` on the dispatcher) if at least 110 min remain;
  otherwise it notifies what is missing. Once per landing
  (`input_datetime.pre_arrival_clean_retry_for`).
- **Nothing else stacks on the queue that day:** `binary_sensor.pre_arrival_clean_day`
  makes `vacuum_on_trip` (13:00) and the daily laundry-room litter pass
  (`vacuum_laundry_room_daily_litter`) skip. Both are `not on` checks, so an unavailable
  sensor never stops them.
- **Queued requests are re-validated when dequeued.** `x40_ultra_main_level_policy_clean`
  is `mode: queued`, and script-level `variables:` render at invocation, so a request that
  waited behind a long run used a stale `mop_due` and re-mopped right after a finished
  mop; and nothing stopped it starting after you arrived (both observed 2026-10-09). The
  dispatcher now computes its decisions as its fi<private_home_airport_secondary_code> action, and drops a request that has
  passed its `expires_at`, or that has `require_away` while `bayesian_occupant_home` is not
  confirmed `off`. Away-triggered trip launches set both; the litter pass sets a 2 h expiry.
  `vacuum_return_home` still only docks the running robot: it must not `script.turn_off`
  the dispatcher, because stopping it mid-run would skip the CleanGenius restore.

Tune the lead with `input_number.pre_arrival_clean_lead_minutes` if the measured cycle time
changes (for example a larger floor plan or a different mop mode), keeping
`lead - buffer >= 195` so the scheduled start still gets the full cycle. Change how early
it must be finished with `input_number.pre_arrival_clean_buffer_minutes`.

## Guest Cat Check (Front Door)

While `input_boolean.trip` is on and `binary_sensor.bayesian_occupant_home` is off,
unlocking `lock.front_door_lock` (`trip_guest_door_unlock_open_house`) turns
`switch.basement_water_shutoff` on, turns off the indoor camera motion-detection
switches, disarms `alarm_control_panel.home_alarm`, and
sets `input_boolean.trip_guest_visit_active`. Locking the door again
(`trip_guest_door_lock_close_house`) turns the water back off, re-arms the
alarm and camera motion detection (retrying up to 3 times and only clearing the
flag once water, alarm and both camera switches are verified; otherwise it keeps the flag and notifies), but only if that flag is set, so the owner's own return never re-arms.
`trip_guest_visit_clear_on_return` clears the flag when you return home or trip
mode ends, so a stale flag never carries into the next trip.
Unlocking also docks all robot vacuums (`script.vacuum_dock_all_robots`, retried
and verified for the den and X40, which must report `docked` or `idle`; the upstairs robot has no HA state entity, so it
is docked but not verified), turns the basement grow light off through
`catnip_grow_light_reconcile`, and
every final vacuum start boundary in `packages/xiaomi_robot_vacuum.yaml` vetoes
while the flag is on, so queued or preparing runs cannot start. Both guest-visit automations use `mode: restart`, so a real lock or unlock during
the startup settle delay supersedes the startup run instead of being dropped.
Both also run at Home Assistant start. Their trip, presence
and flag checks for that path run after a 1-minute settle delay (state-triggered
runs check immediately): with a restored visit flag, an unlocked door reconciles to the open state
and a locked door to the secured state. Both the unlock and relock sequences re-check the door, trip mode, presence and
the visit flag before each attempt, before each state-changing step and after each
wait (a single in-flight service call can still complete after a concurrent
transition), and abort if the visit
state has changed. `vacation_lights_on` (including after its random delay) and
`vacation_lights_off` are also vetoed during a visit. While the flag is on, `vacuum_on_trip` and `vacuum_flying_home` are vetoed.
`water_shutoff_on_trip` skips its 4-hour shutoff while the flag is on; the relock
shuts the water off instead. If the alarm does not disarm on unlock, a push says so.

Trigger source: `lock.front_door_lock` is a virtual optimistic template lock backed
by `input_boolean.front_door_lock`; nothing in HA reads the physical deadbolt. The
guest visit therefore starts only when that virtual lock is unlocked (HomeKit,
Siri, a dashboard button), not from the keypad or thumbturn. Retarget both
automations if a real lock entity is added.

## Manual Verification

1. Turn `input_boolean.trip` on and confirm `switch.vacation_simulation` turns on.
2. Turn `input_boolean.trip` off and confirm `switch.vacation_simulation` turns
   off and `input_number.random_vacation_light_group` resets to `0`.
3. Simulate the one-hour home watchdog while trip mode is on and confirm it
   emits `trip_mode_resolution_requested` instead of directly clearing vacation
   entities.
4. Run `vacuum_on_trip` with guest mode on and confirm no vacuum starts.
5. Run `vacuum_on_trip` with guest mode off, trip mode on, the house empty, and
   pet policy set to `Acclimation`; confirm no vacuum starts and no success
   notification is sent.
6. After an owner explicitly selects `Unattended`, repeat step 5 and confirm
   `script.vacuum_main_and_upstairs_levels` starts once, the main floor vacuums
   then mops (if due), the upstairs and den robots start, and the den only runs
   with its door closed.
7. With a flight home on the calendar, check `sensor.next_flight_home_arrival` (the landing)
   and `sensor.pre_arrival_clean_start` (landing minus the lead). Under `Unattended`,
   trip on and the house empty, confirm `vacuum_flying_home` fires at that start time,
   the main floor vacuums then mops even if the last mop is under three days old
   (forced mop), the X40 is `docked` before the landing, and neither `vacuum_on_trip` nor
   the laundry litter pass runs that day.
8. Catch-up: set the lead so under 195 but at least 100 minutes remain before landing and
   confirm the trace takes the vacuum-only path (`allow_mop: false`, no mop owed); with
   under 100 minutes it only notifies. Restore the lead afterwards.
9. Call `script.x40_ultra_main_level_policy_clean` with the owner home and
   `require_away: true`, and again with a past `expires_at`; both must be dropped with
   a notification and without touching the robot.
