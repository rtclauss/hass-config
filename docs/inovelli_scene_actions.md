# Inovelli Scene Action Map

This map records deliberate multi-tap behavior on high-traffic Inovelli
switches. Single taps remain native or keep their existing load-control
automation; scene actions must not make ordinary operation surprising.

| Action entity | Gesture | Behavior | Safety contract |
| --- | --- | --- | --- |
| `sensor.laundry_wall_switch_action` | Up single | Keep the normal light-on behavior and surface one pending washer or dryer reminder with a local light flash plus notification. | The reminder branch runs only for a newly completed, unsurfaced load. Repeated entries do not duplicate the alert, and no motion sensor is required. |
| `sensor.laundry_wall_switch_action` | Up double | Acknowledge a completed washer or dryer load. The washer reminder boolean is cleared so `washer_cleared` returns it to `IDLE`; the dryer state is set directly to `IDLE`. | Runs only while the washer reminder is active in `CLEAN`, `REMINDED`, or `MUSTY`, or the dryer is `CLEAN` or `REMINDED`; it does nothing while both machines are idle or running. |
| `sensor.garage_overhead_switch_action` | Up double | Open `cover.garage_door`. | Runs only while the door is fully closed; transitional and unavailable states do nothing. |
| `sensor.garage_overhead_switch_action` | Down double | Close `cover.garage_door`. | Runs only while the door is fully open; transitional and unavailable states do nothing. |
| `sensor.hall_transition_switch_action` | Up double | Apply the current Hallway Adaptive Lighting target to `light.hall_all`. | Uses the shared adaptive-light helper and leaves single-tap local load control unchanged. |
| `sensor.hall_transition_switch_action` | Down double | Turn off `light.hall_all` with a short transition. | A deliberate path-wide off action; it does not alter occupancy policy or single-tap behavior. |

## Adding another mapping

Use the switch's stable `sensor.*_action` entity with explicit state triggers
and trigger IDs. Prefer native state conditions for prerequisites, keep
single-tap load control intact, document no-op states, and add regression
coverage for the trigger, target, and safety guard.
