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
- Presence: `binary_sensor.bayesian_zeke_home`
- Distance threshold: `input_number.trip_trigger_radius_miles`
- Calendar sensors: `binary_sensor.planned_vacation_calendar`,
  `binary_sensor.planned_work_trip_calendar`, and
  `sensor.ecobee_calendar_vacation_schedule`
- Flight/calendar trigger: `calendar.ryan_claussen`
- Reconciliation events: `trip_mode_resolution_requested`

## Side Effects

- Trip enable starts vacation simulation through `script.house_transition`.
- Trip disable stops vacation simulation and resets the random vacation light
  group through `script.house_transition`.
- Away lighting remains in `vacation_lights_on` and `vacation_lights_off`.
- Travel vacuuming remains in `vacuum_on_trip` and `vacuum_flying_home`.
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

## Guest Cat Check (Front Door)

While `input_boolean.trip` is on and `binary_sensor.bayesian_zeke_home` is off,
unlocking `lock.front_door_lock` (`trip_guest_door_unlock_open_house`) turns
`switch.basement_water_shutoff` on, turns off the indoor camera motion-detection
switches, disarms `alarm_control_panel.home_alarm`, and
sets `input_boolean.trip_guest_visit_active`. Locking the door again
(`trip_guest_door_lock_close_house`) turns the water back off, re-arms the
alarm and camera motion detection (retrying up to 3 times and only clearing the
flag once water, alarm and both camera switches are verified; otherwise it keeps the flag and notifies), but only if that flag is set, so the owner's own return never re-arms.
`trip_guest_visit_clear_on_return` clears the flag when you return home or trip
mode ends, so a stale flag never carries into the next trip.
Unlocking also docks all robot vacuums (`script.vacuum_dock_all_robots`). Both the unlock and relock sequences re-check the door, trip mode, presence and
the visit flag before each attempt and after each wait, and abort if the visit
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
7. Run `vacuum_flying_home` under `Unattended` and confirm the main floor mops
   even when the last mop is under three days old (forced mop).
