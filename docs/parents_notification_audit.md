# Parents' notification audit

The owner clarified that the task concerns notifications delivered to the owner,
not changes to other household members' alerts. Keep the safe-arrival message.
Only interrupt for work or a decision that needs attention, with useful buttons
and links. This follows [notification routing issue #107](https://github.com/rtclauss/hass-config/issues/107)
and the owner's installation changes in [PR #1224](https://github.com/rtclauss/hass-config/pull/1224).

## Home Assistant findings

The separate installation reports Home Assistant 2026.11.2. All 13 automation
definitions were enumerated; configuration search found seven notification
producers with no skipped automation/script definitions. AppDaemon is stopped.
The persistent-notification snapshot contained only HomeKit pairing information;
that snapshot does not measure push-notification traffic.

| Producer | Priority / classification | Owner action now | Result |
| --- | --- | --- | --- |
| Fridge power-status off | Important unresolved equipment exception | Check the appliance and its power supply when the status goes off | Add a direct owner alert with status and power-reading links |
| Safe-arrival confirmation | Explicitly retained reassurance | No task; owner requested keeping it | Preserve the message, audience, and arrival flag handling |
| Trip enabled | Routine successful state change | None after the automation handled it | Preserve others' existing route; no blanket suppression |
| Trip ended | Routine successful state change | None after the automation handled it | Preserve others' existing route; no blanket suppression |
| Random vacation light group / off time | Debug/scheduling information | None | Preserve existing delivery; it is not currently routed to the owner's phone by the configured group |
| Vacation lights on | Routine successful operation | None | Preserve existing delivery; do not interfere with simulation |
| Vacation lights off | Routine successful operation | None | Preserve existing delivery; do not interfere with simulation |

### Recipient routing gap

The active root configuration includes `notify.yaml`. Its `all` group names one
legacy mobile service, absent from the current complete notify-service inventory.
It does not name the owner's currently registered phone notifier. Thus the five
routine `notify.all` producers do not explain the owner's noise through that
configured route. Do not rewrite that group or mute family alerts based on an
assumed audience.

The fridge warning also used this legacy group. The focused change adds a direct
owner phone route while retaining the original action and payload verbatim. The
new send tolerates delivery errors so it cannot block existing actions. Its
incident tag is installation-specific to avoid cross-home mobile tag collisions.

The new message describes the power-status sensor's report and asks for a check;
it does not claim that a network or sensor state proves refrigeration stopped.
Both buttons open status/readings; neither toggles power nor acknowledges physical
work. The status was on at the audit snapshot, so no fridge-power task was then
reported. One legacy power reading was implausible; the navigation uses a separate
existing power-reading entity rather than that reading. This change does not
repair meter scaling or create temperature-based safety coverage.

## Scrypted scope and deferred work

The owner confirmed Scrypted notifications exist in both environments. Both
Scrypted apps were found running. The parents' embedded management console showed
Disconnected and no devices, so notification subscriptions, schedules, zone
filters, and user mappings could not be verified. The owner explicitly deferred
Scrypted work. No Scrypted notification settings were changed.

When resumed, apply the owner's stated preference to the owner's notifier/user
only: retain doorbell presses, people approaching the entrance while someone is
home, and actionable security/recording failures. Ordinary motion, animals, and
routine camera activity are lower priority. Identify the actual entrance zone and
preserve other users' delivery. Do not invent a zone or mute all person detections.
Compare Scrypted event/incident identifiers with HA notifications before claiming
or removing duplicate delivery. Recording itself is a separate setting.

Scrypted can deliver through both its app and the Home Assistant Companion app;
the [official integration guide](https://docs.scrypted.app/home-assistant.html#notifications)
places notification options on the linked notifier/user in the management console.
The earlier HA-only audit is not a complete cross-application notification audit.

## Repeatable change and verification

`scripts/notification_attention.py` prepares the recipient-specific edit from a
fresh automation export. The caller must supply the verified expanded audience,
explicit owner service, installation-specific tag, and existing entity IDs. The
transform rejects an already-covered recipient and ambiguous action structures.
It performs no network calls or device operations. Keep real exports and audience
values in ignored local storage; committed tests use synthetic identities.

Before applying, save the current automation and verify it has not changed since
the export. Write through the Home Assistant config API, then read back the saved
definition and compare its original trigger/actions and new owner route. Do not
manually trigger the automation to test: that would send a real alert. Verify the
owner notifier and both destination entities exist, and run the configuration
check. Rollback writes the saved original through the same config API; it does not
restore the entire installation or change notification groups.

Tests cover old/new HA action syntax, preserved original audience/payloads and
operating steps, duplicate-recipient rejection, URI buttons on Apple/Android,
mobile-command rejection, malformed destinations, and ambiguous config shapes.
Live device taps still require verification on a naturally occurring alert.

## Applied result

The recipient-specific fridge update was saved through the MCP config API and
read back successfully. The original trigger and original actions are preserved.
All six other notification-producing automations were fetched again and compared
with the audit exports; they are unchanged, including safe arrival. Configuration
validation passed, and the fridge automation remains enabled. The owner service
and destination entities were verified from the running installation; automatic
reference checking was unavailable because the optional HA MCP tools component
was not installed. No test notification or physical operation was sent.

The synthetic regression matrix has 18 cases and 100% statement/branch coverage
for the recipient-specific transformation module. This does not claim end-to-end
mobile delivery or phone-side navigation coverage.
