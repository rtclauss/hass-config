# Cat-safe robot-cleaning policy

This policy is the durable safety boundary for robot vacuuming and mopping.
It supplements the global guest-mode rule in `docs/room_intent.yaml`; guest
mode always vetoes automatic vacuuming regardless of the selected pet policy.

## Modes

- **Acclimation** is the fail-closed mode: no automatic cleaning may start.
  Entering this mode immediately calls `script.vacuum_dock_all_robots` for the
  den, main-level X40, and upstairs Valetudo robot. It is no longer forced on
  after every restart — the helper restores its last selected value across
  reloads/restarts — but HA startup still docks all robots as a safety
  reconcile, and any unavailable/unknown helper state fails closed.
- **Supervised** reserves room-limited, one-robot, vacuum-only cleaning for an
  owner who has inspected the area and is present to watch both cats. The
  source-controlled foundation does not automatically start a supervised run.
- **Unattended** is the only mode that permits automatic launch and error-retry
  paths. Selecting it is an explicit owner decision after both cats remain
  relaxed through repeated supervised runs and the floor has been inspected.

The policy must never promote itself. An unavailable, unknown, missing, or
unexpected helper state fails closed because automatic boundaries require the
exact `Unattended` state.

## Environmental prerequisites

- Keep a robot-free refuge accessible throughout a run, with enough safe
  places and resources for both cats.
- Clear waste, vomit, string toys, cables, spills, and other hazards before
  any supervised or unattended run.
- Camera, BLE, and room-presence data may add context but never prove that a
  cat or floor is safe.
- Guest mode, bed occupancy, den-door, map, stall, error-reporting, and
  arrival-to-dock protections remain independent guards.

## Current implementation boundary

Issue #890's first implementation stage gates all seven known automatic launch
or retry automations, the shared whole-floor launchers, and the X40 mop path.

Under `Unattended`, the main floor is cleaned as two distinct passes — a full
vacuum (cleaning mode `sweeping`), then a full mop (cleaning mode `mopping`) —
rather than the interleaved `mopping_after_sweeping` mode, so dry debris is fully
removed before any water is applied. The mop runs when it is due (pending, or the
last mop is at least three days old); the flying-home path additionally forces
the mop. Only the X40 mops; the upstairs and den robots are vacuum-only.

Dashboard controls, approval-gated unattended runs, area mapping, and a quiet
one-area supervised launcher remain follow-up work because they require validated
live mappings and native Home Assistant UI/API changes; do not edit `.storage`
files directly.

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
