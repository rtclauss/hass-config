# Room Confidence Occupancy

Issue: `#108`

## Summary

The room-confidence layer turns existing room occupancy booleans into weighted
scores instead of treating every source as equally trustworthy.

Current rooms:

- Bedroom
- Office
- Den
- Basement

## Inputs

Each room score is capped to `0-100` and forced to `0` when both
`person.ryan` and `binary_sensor.bayesian_zeke_home` say the house is empty.

Signals currently blended:

- Bermuda room/floor hints from `sensor.iphone_17_pro_area`,
  `sensor.apple_watch_ultra_2_area`, `sensor.iphone_17_pro_floor`, and
  `sensor.apple_watch_ultra_2_floor`
- Existing room occupancy booleans such as
  `binary_sensor.office_occupancy_2` and `binary_sensor.den_occupancy_2`
- Bed occupancy from `binary_sensor.bayesian_bed_occupancy`
- Office proxy presence from `binary_sensor.ryan_office_presence`

## Weighting

- Room occupancy is the strongest generic signal and contributes `55`.
- Bedroom bed occupancy contributes `70` so bed-only presence still reaches a
  confident score.
- The phone is the primary BLE room signal and contributes `45` for modeled
  room matches (`35` area + `10` floor in the basement).
- The watch is corroboration only and contributes `10` for area matches (`5`
  floor in the basement).
- When both phone and watch agree on the same room, the score gets a small `+5`
  corroboration bump.
- Phone disagreement is penalized harder than watch disagreement because the
  phone is assumed to be carried more consistently.

That mismatch penalty is intentional. It prevents stale motion/occupancy
booleans from winning outright when both Bermuda devices agree that Ryan is in
another room.

That also means a watch left on a charger or nightstand should not keep a room
in the `likely` band by itself.

## Thresholds

- `0-24`: `clear`
- `25-49`: `possible`
- `50-79`: `likely`
- `80+`: `certain`

Binary sensors such as `binary_sensor.office_confident_occupancy` switch on at
`50+`.

## Downstream Usage

`automation.office_lights_morning_on_vacancy_off` now keys off
`binary_sensor.office_confident_occupancy` instead of raw office occupancy
signals. That lets Bermuda disagreement suppress obvious false positives while
still allowing BLE-only and motion-only occupancy to count.

## Manual Validation

1. BLE only: move both Bermuda devices into a modeled room with motion clear and
   confirm the room reaches `50+`.
2. Watch only: leave the watch in a room without the phone and confirm the room
   stays below `50`.
3. Motion only: trigger a room occupancy sensor with Bermuda room hints absent
   and confirm the score still reaches `50+`.
4. Bed only: confirm bedroom confidence reaches `50+` when only
   `binary_sensor.bayesian_bed_occupancy` is on.
5. Empty house: set `person.ryan` to `not_home` and
   `binary_sensor.bayesian_zeke_home` to `off`, then confirm all room scores go
   to `0`.
6. Signal loss: mark one Bermuda room sensor unavailable and confirm the score
   drops but does not collapse to `0` when another positive signal remains.

## Notification Guidance

An actionable “which room are you in?” notification is not part of the base
model. With Bermuda disagreement penalties in place, those prompts are more
useful as a temporary diagnostics tool for ambiguous `25-49` scores than as a
normal control path.
