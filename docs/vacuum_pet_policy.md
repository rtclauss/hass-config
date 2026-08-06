# Cat-safe robot-cleaning policy

This policy is the durable safety boundary for robot vacuuming and mopping.
It supplements the global guest-mode rule in `docs/room_intent.yaml`; guest
mode always vetoes automatic vacuuming regardless of the selected pet policy.

## Modes

- **Acclimation** is the fail-closed default after every Home Assistant reload
  or restart. No automatic cleaning may start. Entering this mode immediately
  calls `script.vacuum_dock_all_robots` for the den, main-level X40, and
  upstairs Valetudo robot.
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
The previous flying-home forced mop is removed. Dashboard controls, approval-
gated unattended runs, area mapping, and a quiet one-area supervised launcher
remain follow-up work because they require validated live mappings and native
Home Assistant UI/API changes; do not edit `.storage` files directly.
