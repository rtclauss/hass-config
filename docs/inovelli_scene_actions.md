# Inovelli Scene Action Map

This map records deliberate multi-tap behavior on high-traffic Inovelli
switches. Single taps remain native or keep their existing load-control
automation; scene actions must not make ordinary operation surprising.

| Action entity | Gesture | Behavior | Safety contract |
| --- | --- | --- | --- |
| `sensor.laundry_wall_switch_action` | Up double | Acknowledge a completed washer load by clearing `input_boolean.washer_reminder_active`; the existing `washer_cleared` automation returns the washer state to `IDLE`. | Runs only while the reminder is active and the washer is `CLEAN`, `REMINDED`, or `MUSTY`; it does nothing during `IDLE` or `CLEANING`. |
| `sensor.garage_overhead_switch_action` | Up double | Open `cover.garage_door`. | Runs only while the door is fully closed; transitional and unavailable states do nothing. |
| `sensor.garage_overhead_switch_action` | Down double | Close `cover.garage_door`. | Runs only while the door is fully open; transitional and unavailable states do nothing. |
| `sensor.hall_transition_switch_action` | Up double | Apply the current Hallway Adaptive Lighting target to `light.hall_all`. | Uses the shared adaptive-light helper and leaves single-tap local load control unchanged. |
| `sensor.hall_transition_switch_action` | Down double | Turn off `light.hall_all` with a short transition. | A deliberate path-wide off action; it does not alter occupancy policy or single-tap behavior. |

## Adding another mapping

Use the switch's stable `sensor.*_action` entity with explicit state triggers
and trigger IDs. Prefer native state conditions for prerequisites, keep
single-tap load control intact, document no-op states, and add regression
coverage for the trigger, target, and safety guard.
