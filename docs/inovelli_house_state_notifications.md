# Inovelli house-state notifications

The hall transition, laundry wall, and garage overhead Inovelli LED bars share
one deterministic house-state status. The coordinator always applies the first
active signal in this priority order:

| Priority | Signal | Active states | LED effect |
| --- | --- | --- | --- |
| 1 | Front door lock | `unlocked`, `unlocking`, `open`, `opening`, or `jammed` | Red pulse |
| 2 | Garage door | `open` or `opening` | Orange open/close |
| 3 | Mail waiting | `input_boolean.mail_delivered` is `on` | Cyan solid |

When the active signal clears, the coordinator immediately falls through to
the next active signal. When none remain, it sends `Clear Effect`, which removes
the notification without replacing the switches' normal day/night LED profile.
`unknown` and `unavailable` states do not claim the LED bars.

Trip mode remains the higher-level owner of all Inovelli LEDs. While
`input_boolean.trip` is on, the coordinator makes no changes and the existing
trip policy keeps every effect cleared. Leaving trip mode restores the normal
LED profile and then reapplies the current house-state winner.

The existing switch-reset flow temporarily owns the bars with its ten-minute
Aurora success effect. When that script finishes, the coordinator waits for the
Aurora duration and then reapplies the current winner. Any house-state change
during that wait restarts the coordinator and applies the new winner immediately.

## Expansion rules

- Add new signals to `script.apply_inovelli_house_state_notification` in their
  intended priority position; the first matching branch wins.
- Use native state conditions with explicit actionable states so an unavailable
  entity does not become a false alert.
- Add targets only after verifying that the live entity is an Inovelli device
  supported by the checked-in blueprint.
- Keep the clear action as the default branch so resolved states cannot leave a
  stale effect behind.

## Manual verification

Perform these checks only when trip mode is off:

1. Toggle each source through one active and one resolved state, then confirm all
   three target switches show and clear the documented effect.
2. Activate mail and garage together; garage must win, then mail must appear when
   the garage closes.
3. Add the unlocked front door to that combination; red must win until the lock
   returns to `locked`.
4. Enable trip mode and confirm all effects clear. Disable it and confirm the
   current winning signal returns.
