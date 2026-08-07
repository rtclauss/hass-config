# House Transition Framework

Issue: `#109`

## Summary

`script.house_transition` is the single entrypoint for shared house-mode changes.
Existing automations now delegate to it instead of each one directly managing
lights, locks, covers, climate, guest media grouping, or trip-mode vacation
simulation.

Base modes:

- `home`
- `away`
- `night`

Explicit overrides:

- `input_boolean.guest_mode`
- `input_boolean.trip`

## Entrypoint

```yaml
- action: script.house_transition
  data:
    mode: away
    reason: leave_home
```

Common optional fields:

- `light_scene`
- `light_transition`
- `extra_scene`
- `notify_message`
- `guest_mode`
- `trip_mode`
- `apply_lights`
- `apply_security`
- `apply_climate`
- `apply_media`
- `apply_trip_policy`

## Current Delegates

- `packages/zone.yaml`
  `cloudy_home_arrival`, `default_arrive_home`,
  `turn_on_lights_at_night_when_i_get_home`,
  `turn_on_bedroom_lights_at_night_when_i_get_home`,
  `run_verified_departure`
- `packages/guest.yaml`
  guest-mode enable/disable and guest climate refresh automations
- `packages/trips.yaml`
  trip-mode manager enable/disable paths, startup reconciliation, and the
  one-hour home watchdog

## Trip Mode

Trip-mode behavior is documented in `docs/trip_mode_orchestration.md`. The
important contract is that automated trip resolution delegates to
`automation.trip_mode_manager`, and the manager calls `script.house_transition`
with `apply_trip_policy: true` so vacation simulation stays in sync with
`input_boolean.trip`.

## Verified Departure

`automation.run_verified_departure` starts only from the canonical
Bayesian empty-house event and delegates to `script.departure_integrity`.
It confirms the house is empty from `binary_sensor.bayesian_zeke_home` rather
than the derived GPS tracker, which can still read `home` at that moment.
That script:

- stops immediately when guest mode is active or resident presence returns;
- calls `script.house_transition` with `mode: away` and trip-policy handling;
- waits for the normal shutdown to settle, then retries available lock, cover,
  light, fan, media, and camera exceptions once;
- never sends service calls to targets that are `unknown` or `unavailable`;
- sends one final notification containing every remaining security, egress,
  lighting, media, fan, camera, and trip-policy exception.

The front exterior lights remain protected. The former independent garage and
egress departure notifications were consolidated into the final integrity
summary so a single departure cannot produce duplicate alerts.

## Manual Verification

1. Trigger `script.house_transition` twice with the same `mode` and confirm no
   unsafe repeat behavior occurs.
2. Leave home with `input_boolean.guest_mode` off and confirm the lock, garage,
   leave-home scene, camera scene, media pause/off, fan, and light shutdown run.
   Confirm a normal successful departure sends no notification.
3. Leave home with `input_boolean.guest_mode` on and confirm away tracking
   updates without running the destructive leave-home actions.
4. Arrive home during the day and confirm the normal arrival scene and Ecobee
   program resume still run.
5. Arrive home at night and confirm the night-arrival scene still runs; repeat
   with the bedroom-prep automation path.
6. Toggle `input_boolean.guest_mode` on and off and confirm Sonos grouping and
   the Ecobee guest preset reapply without retriggering arrival/departure
   lighting.
7. Toggle `input_boolean.trip` on and off and confirm
   `switch.vacation_simulation` and
   `input_number.random_vacation_light_group` stay in sync.
8. Temporarily make one target entity unavailable and confirm the script keeps
   applying the remaining actions, does not call the unavailable target, and
   reports it once in the final exception summary.
9. Leave one available target in the wrong state, confirm it receives one retry,
   and confirm only the final state is reported if the retry does not succeed.
