# Robot cleaning

Three robots clean the house:

| Robot | Entity | Floor | Mops |
| --- | --- | --- | --- |
| Dreame X40 Ultra | `vacuum.x40_ultra` | Main level | Yes |
| Valetudo upstairs | `vacuum.valetudo_upstairs_vacuum` (driven over MQTT) | Upstairs | No |
| Valetudo den | `vacuum.valetudo_den` | Den | No |

The cat pet-safety policy (`input_select.vacuum_pet_policy`, Acclimation /
Supervised / Unattended) was removed at the owner's request. Cleaning is now
bounded only by the guards below.

## Guards

- Guest mode (`input_boolean.guest_mode`) and a trip guest visit
  (`input_boolean.trip_guest_visit_active`) veto every start, automatic or
  manual, per `docs/room_intent.yaml`.
- The den robot starts only through `script.vacuum_den_guarded_start`, which also
  requires the den doors confirmed closed.
- Automatic 13:00 runs skip while the bed is occupied.
- Arrival-to-dock (`vacuum_return_home`), map guards, stall monitoring, and
  error reporting remain independent protections.
- An HA restart no longer docks every robot; boot-time automations check that a
  robot is at rest before touching it.

## Dashboard controls

The Cleaning-v2 dashboard view never calls `vacuum.start`, `vacuum.clean_area`,
or a tile card's native start, because those bypass the guards above and, on the
X40, the CleanGenius-off / forced-sweeping flow (a native start could mop).
Pause and return-to-dock are safe and may stay native.

- `script.vacuum_manual_start` (`robot: main | upstairs | den | all`) hands off
  to `vacuum_main_level_full_floor`, `vacuum_upstairs_full_floor`, and
  `vacuum_den_guarded_start`. The main level mops only when a mop is due, the
  same as the automatic runs.
- `script.vacuum_clean_room` (`room: <HA area id>`) vacuums one room, vacuum-only.
  X40 rooms go through the dispatcher (`kind: segment`); upstairs rooms go
  through `vacuum_upstairs_segment_guarded`. The room is a call-time field, so a
  queued request can only clean the room that was tapped.
- `script.vacuum_dock_all_robots` docks every robot.
- `sensor.vacuum_start_blocker` (`ok`, `guest_mode`, `trip_guest`; attribute
  `den_doors_closed`) lets buttons show why a start would be refused. The
  scripts remain the enforcement point and notify with the reason when they
  refuse.

| Room id | Robot | Segment |
| --- | --- | --- |
| `dining_room` | X40 | 1 |
| `powder_room` | X40 | 2 |
| `hallway` | X40 | 3 |
| `kitchen` | X40 | 4 |
| `den` | X40 | 5 (vendor name "Living Room") |
| `laundry_room` | X40 | 6 |
| `bedroom` | Upstairs | 7 |
| `guest_room` | Upstairs | 5 |
| `bathroom` | Upstairs | 4 |
| `upstairs_hallway` | Upstairs | 6, 1 |
| `office` | Upstairs | 2 |

The X40 ids follow the segment-to-area mapping on the X40 entity's settings.

## Main-level two-pass cleaning

The main floor is cleaned as two distinct passes — a full vacuum (cleaning mode
`sweeping`), then a full mop (cleaning mode `mopping`) — rather than the
interleaved `mopping_after_sweeping` mode, so dry debris is fully removed before
any water is applied. The mop runs when it is due (pending, or the last mop is at
least three days old); the flying-home path additionally forces the mop. Only the
X40 mops; the upstairs and den robots are vacuum-only.

Every X40 run goes through one `mode: queued` dispatcher, so a request can wait hours
behind a ~3 h cycle. The dispatcher therefore re-validates a request when it is
**dequeued**: its mop decision is computed then (not at queue time, when
script-level `variables:` would have been rendered), and a request is dropped if it
has passed its `expires_at`, or if it is away-only (`require_away`) and the owner is
not confirmed away. Fail closed: an unparseable `expires_at`, or unknown/unavailable
presence on an away-only request, drops it. `allow_mop: false` forces a vacuum-only
pass. The flying-home clean uses these to finish before landing and never start
after you are home (see `docs/trip_mode_orchestration.md`).

A pass is credited (`x40_ultra_vacuum_pass_completed`, `x40_ultra_last_vacuumed_at`,
`x40_ultra_last_mopped_at`) only when `task_status` reaches `completed` after the dock.
The passes wait up to 2 min for it, because it can lag the dock by seconds (2026-10-26),
and never credit a run during which `vacuum_return_home` or `vacuum_dock_all_robots`
fired. `kind: mop_only` on the dispatcher runs just the mop pass; it is only for a caller
that has confirmed the floor's vacuum pass already completed.

## Known limitation: external (non-HA) runs

The deterministic X40 flow disables CleanGenius, selects a cleaning mode, runs,
and restores CleanGenius. Home Assistant cannot atomically lock a physical robot
against a run started *outside* HA (the vendor phone app or the robot's own
button). The flow guards this as tightly as HA allows — it refuses to start when
the robot is already cleaning, rechecks that it is at rest before disabling
CleanGenius, before selecting the mode, and before starting, and defers restoring
CleanGenius (fail closed) until the robot is at rest again so it never restores on
top of an external run. A sub-second residual remains: `prepare` disables
CleanGenius as its first action, so an external run beginning in the instant
between a rest check and that mutation can briefly see CleanGenius off. This is
self-healing — the next deterministic run restores CleanGenius — and cannot be
fully eliminated without a control channel that external runs also respect. It is
accepted as a documented limitation rather than chased further.
