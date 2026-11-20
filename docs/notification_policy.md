# Notification policy

The owner requested: **Only notify me when I need to act**, with useful buttons
and links. This applies to both
homes. The parents' installation needs a separate audit when access is available;
the first implementation covers this repository's installation only.

Push notifications should describe an actionable exception. Routine reports,
successful automatic actions, and changing measurements belong in Home Assistant.
An existing problem should not create another interruption merely because its
percentage, wording, ordering, or affected-device count changed. A new affected
device can require a new action even when the total count stays the same.

## First implementation

- Battery levels below 20% update the existing Home Assistant notice only.
- Levels below 10% push when another device enters the affected set.
- Offline battery sensors push for newly affected devices, not recoveries.
  This remains an availability warning, not proof that a battery is dead.
- Percentage changes and reordering update local notices without another push.
- Startup synchronization and unavailable monitor recovery do not replay pushes.
- An empty affected set clears the local notice and the existing mobile tag.
- Routine sump runtime and weekly energy reports update one local notice each.
- Sump high-water, leak, alarm, and severe-weather alerts still push. A leak
  sensor that dries silently replaces its own wet alert (same per-sensor tag,
  iOS `passive`, Android `alert_once`), so the record stays without a new
  interruption.
- Sump high-water alerts link to the level only. They do not link to the pump
  switch, whose dialog would put an off toggle one tap away during a flood.
- Open-window rain warnings name the open windows when the
  `binary_sensor.any_window_open` `open_windows` attribute lists them.
- The laundry reminder opens the machine its message is about (the washer
  when both loads wait).
- Task notifications for leaks, alarms, sump high water, garage, batteries,
  offline devices, laundry, open-window rain risks, and salt have useful buttons
  and tap destinations. Both `url` (Apple) and `clickAction` (Android) are supplied.
- Buttons open the relevant controls/status rather than firing an unhandled
  event or pretending physical work has been completed. Existing task handlers
  such as delivery retrieval, salt purchase, and diffuser replacement stay intact.
- Playlist selection goes to the logbook instead of a phone push. Blind
  forensics log every move with its context. Only an open with neither a parent
  nor a user context (the issue #781 signature) keeps one overwriting Home
  Assistant notice, `blind_forensics_unattributed_open`, and never a phone push.
  A physical remote press can match that signature too, so check the logbook
  context before treating a notice as the culprit.

The [audit](notification_audit.md) classifies the remaining sources and records
runtime gaps, current task relevance, and follow-up work. Navigation uses the
[Companion app URL contract](https://companion.home-assistant.io/docs/notifications/notifications-basic/#opening-a-url)
and [URI action buttons](https://companion.home-assistant.io/docs/notifications/actionable-notifications/#building-actionable-notifications).

Battery identity comparison uses the existing machine-readable summary lines
(`- sensor.example_battery: 9%`), shared through one YAML-anchored condition.
If that format changes, update the comparison and regression cases together.

This is the first reduction, not a complete routing overhaul. Brief offline flaps
can still notify when a device rejoins the affected set; retired devices still
need inventory cleanup. The audit identifies remaining changes to chore reminders, maintenance reminders,
travel status, and other notification producers. No daily
digest or new notifications are added.

## Validation and rollback

Run `uv run --with pytest pytest`. The decision matrix exercises percentage drift,
new devices, same-count replacement, recovery, ordering, and unavailable/startup
states for both remaining battery push paths. Routing assertions cover early
warnings, routine reports, and preserved sump high-water alerts. This is YAML
decision coverage; it is not a claimed percentage of live delivery coverage.

For deployment, preserve every touched source and its private rendered output.
The first pass changed the battery package and utilities template/output; the
second adds controls and diagnostic routing across the files in the PR.
Compare the live sources with the patch base;
apply only these edits and render with the installation's private mapping.
Validate Home Assistant configuration, then reload automations. Do not replace
live configuration with synthetic test output. Test the condition with synthetic
trigger data through the template API without sending notifications.

Rollback restores the corresponding saved sources and private outputs, then
reloads automations after checking the configuration. No entity IDs, helpers,
or other device behavior are migrated.

Live validation: Home Assistant `check_config` passed before both reloads.
The battery condition was evaluated through the live API using synthetic drift,
new-device, and recovery cases. All notification destinations were checked for
entity existence; the sump-level entity remains unavailable. No test pushes or
physical device operations were sent. Phone-side button taps still need a real
notification to verify the client experience. Four old blind diagnostic notices
were dismissed after the log-only watcher was loaded.
