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
is suppressed when `input_boolean.guest_mode` is on, matching
`docs/room_intent.yaml` guidance that automatic vacuuming should not intrude on
guest-capable rooms. Trip-mode vacation simulation is still allowed because it is
an exterior/common-area presence signal and is idempotently controlled by
`script.house_transition`.

## Manual Verification

1. Turn `input_boolean.trip` on and confirm `switch.vacation_simulation` turns on.
2. Turn `input_boolean.trip` off and confirm `switch.vacation_simulation` turns
   off and `input_number.random_vacation_light_group` resets to `0`.
3. Simulate the one-hour home watchdog while trip mode is on and confirm it
   emits `trip_mode_resolution_requested` instead of directly clearing vacation
   entities.
4. Run `vacuum_on_trip` with guest mode on and confirm no vacuum starts.
5. Run `vacuum_on_trip` with guest mode off, trip mode on, and the house empty;
   confirm `script.vacuum_main_and_upstairs_levels` starts once.
