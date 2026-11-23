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
| `sensor.hall_transition_switch_action` | Up double | Turn on `light.hall_all` and `light.hall_stairway_bulbs` through their respective Hallway and Stairway Adaptive Lighting profiles. | Uses `script.hallway_lights_turn_on` and leaves single-tap local load control unchanged. |
| `sensor.hall_transition_switch_action` | Down double | Turn off `light.hall_all` and `light.hall_stairway_bulbs` with a short transition. | A deliberate path-wide off action; it does not alter occupancy policy or single-tap behavior. |
| `sensor.dining_room_wall_switch_action` | Up / down double | Raise (cooler) or lower (warmer) `light.dining_room_all` color temperature by 200 K. | Single taps stay adaptive on/off. |
| `sensor.dining_room_table_switch_action` | Up / down double | Adaptive on / off for `light.kitchen_all`. | Gives the dining table switch a kitchen-wide control without changing its own load. |
| `sensor.kitchen_switch_action` | Up / down held | Step `light.kitchen_all` brightness up or down by 10 while held. | Single taps stay adaptive on/off for the kitchen. |
| `sensor.owner_suite_fan_switch_action` | Up / down double | Increase or decrease `fan.owner_suite` speed. | Single up turns on the ceiling and lamps (plus the bed strip) through adaptive lighting; single down turns the ceiling off. |
| `sensor.office_fan_switch_action` | Up / down double | Increase or decrease `fan.office_ceiling_fan` speed. | Single taps turn `light.office_ceiling` on/off. |
| `sensor.guest_room_fan_switch_action` | Up / down double | Increase or decrease `fan.guest_room` speed. | Single taps turn `light.guest_room_ceiling` on/off. |
| `sensor.basement_bathroom_shower_switch_action` | Up / down double | No mapped action (triggers exist, no branch). | Single taps turn the shower light on/off. |

## Adding another mapping

Use the switch's stable `sensor.*_action` entity with explicit state triggers
and trigger IDs. Prefer native state conditions for prerequisites, keep
single-tap load control intact, document no-op states, and add regression
coverage for the trigger, target, and safety guard.
