# Calm contextual dashboard

Read [Dashboard design guide](dashboard_design.md) for the owner's brief,
design vocabulary, decision rationale, and ongoing agent instructions. This
document covers the implementation, reporting contract, deployment, and soak.

The daily dashboard remains UI-editable Lovelace storage configuration. Home,
Rooms, House, Travel, and More provide stable navigation; the context panel
changes emphasis without moving favorite controls. Existing numeric view
indexes and named paths remain usable. Specialist cards and their capabilities
are retained. Room light/fan/cover cards use native Tiles where supported.

`Calm Home` is scoped to these views. In each client profile select **Calm Home**, then **Auto** to follow the device,
or select Light/Dark explicitly. Selecting the theme in the profile also lets HA
resolve view-theme dark mode correctly; a fixed-appearance backend theme cannot
provide that mode to views on its own. The
existing backend theme automation is not changed. Navbar Card 1.8.0 provides
labelled navigation, with bottom navigation below 1200px, a side rail above it,
safe-area support, and automatic padding. Tile-derived Mushroom Template cards
provide keyboard-accessible room summaries. Shared factories and theme classes
render rooms and read-only readiness rows without instance-specific styling.
Readiness rows share one native, single-column grid panel rather than separate oversized cards. Grouping avoids the legacy stack wrapper's class-placement differences; shared theme rules style the panel surface and row dividers.
Navbar routes lack keyboard semantics in the installed stable release, so native
HA tabs remain available and reveal themselves on keyboard focus. A small shared
card-mod theme rule raises native tile icons/features to 44px; fan controls use
a full row to avoid narrow speed buttons.

The visual follow-up in issue #1169 restores the rendered examples' hierarchy:
context/header and status chips, two-column room cards, compact media/whole-house
panels, then quick controls. Sliders remain available in the relevant controls
and room details. Core HA sidebar visibility remains a native client preference;
More includes Settings, Profile/appearance, and History. The widened desktop
navigation rail reserves 184px through Navbar's padding configuration.

Typography uses one shared JSON card-mod snippet from the composer, with token
values in the theme. Theme-YAML styling did not initialize in the tested client;
do not replace the snippet with that path without verifying a fresh client load.

## Reporting contract

`packages/dashboard_status.yaml` and `custom_templates/dashboard_status.jinja`
contain observation-only reporting. They call no services, send no notifications,
and do not start/retry robots, operate water, change climate, or alter trip mode.
The trigger-based templates require YAML for restored evidence attributes.

- `sensor.dashboard_context`: sleep, return, away, departure, evening, morning,
  home, or unknown. Dates are interpreted in HA's timezone. A future itinerary
  alone never makes an active return context. Sleep takes precedence at home.
- `sensor.dashboard_return_cycle`: associates a return landing with a cleaning
  window derived from the selected landing and existing lead/buffer helpers,
  avoiding races with dependent timestamp sensors. Missing calibration leaves
  the window unknown. Sub-six-hour flight changes retain the cycle identity; a different
  future landing starts a new cycle. A landing that has occurred is retained
  rather than overwritten by a later itinerary. A new trip resets old evidence;
  trip end closes the evidence window. Initial installation cannot reconstruct
  a missed trip-start event and starts conservatively with the observation time.
- `sensor.dashboard_upstairs_activity`: observes the existing retained MQTT
  status topic. Replaying an identical status does not refresh its timestamp.
  Activity and docking are never full-cycle success evidence.
- `sensor.dashboard_readiness_*`: security, climate, water, vacuum_main,
  mop_main, vacuum_den, vacuum_upstairs, and pet_care. Each exposes `reason`,
  `evidence_at`, `source`, and `cycle_id`. Evidence time describes the source
  report or successful pass, not an independent physical inspection.
- `sensor.dashboard_return_readiness`: rolls up the eight required results.
  Unknown, unavailable, interrupted, or missing evidence never becomes complete.

Main-floor vacuum/mop completion uses the existing successful full-floor
timestamps within the associated cycle, excluding results after trip closure.
Guest guards, active owned passes, pending sequences, and missed deadlines are
reported separately. A missed deadline does not prove whether a run was skipped
or interrupted, so its result remains unknown with an explanation.

Den/upstairs sources expose activity without a dependable full-cycle success
result. Feeder schedules/errors do not confirm food dispensing or connectivity.
These results remain unverified until the device integrations expose trustworthy
evidence. No completion signal is invented from a launch, timer, dock, or schedule.

Climate readiness requires a reported target: within one displayed degree of a
single target, or inside the reported heat/cool band. Off mode or missing target
is unknown. This describes the thermostat's current target, not an invented
arrival setpoint. Water is device-reported on/off plus available leak alerts;
the existing trip-end restore timing is unchanged. Flight times are labelled
landing and shown with HA's timezone, never presented as home-arrival ETA.

## Export, apply, and rollback

Use `scripts/calm_dashboard.py --input PRIVATE_BEFORE.json --output PRIVATE_AFTER.json
--root /DASHBOARD-PATH --states PRIVATE_STATES.json` to compose a reviewed change.
Real snapshots, inventories, and runtime mappings belong in the main clone's
gitignored `.private-runtime-backup/` directory, never public Git. The public
fixture contains only synthetic data.

The composer refuses an unrelated first view, preserves original view indexes,
keeps unrelated dashboard fields/templates/cards, and replaces its four generated
destinations without duplication. UI edits are live configuration; do not rerun
against an old export. Export the current dashboard, review the diff, then use
the dashboard API's configuration-hash precondition. Read the saved result back.
Never edit `.storage` or replace a dashboard from a scoped single-view response.

Back up each changed YAML/theme/macro file before deployment. Check HA config,
reload custom templates, reload template entities and themes, and reload Lovelace
resources. Fire `dashboard_status_refresh` once after installation to initialize
the reporting cycle without restarting HA or changing trip state.

Rollback restores the private dashboard snapshot through the API and restores
the captured resource configuration and any overwritten files. Remove only the
new reporting package/macro/theme and reload their integrations. Do not use a
full HA restore. No database migration is involved.

## Verification

Run `uv run --with pytest pytest` and the HA configuration check. Targeted tests
exercise the actual shared Jinja macros with synthetic states/times and the
dashboard composition logic. Include coverage output and scenario coverage in
the PR. Keep `.allium` definitions unchanged and compare behavior to the room,
alarm, night, diffuser, and media policies.

Check phone/tablet/desktop widths, iPad Split View, both appearances, keyboard
focus, text scaling, and action target sizes. Inspect the real dashboard for
custom-card errors, overlap, horizontal overflow, and unsupported controls.
Physical device actions are not part of visual smoke testing. Device-specific
checks that cannot be performed must remain explicitly outstanding during soak.

## Deployment and soak record

The storage dashboard was applied with a fresh configuration-hash precondition
and read back identically (25 views). Private before/after and file backups are
kept in the main clone. The installed stable HACS Navbar Card is 1.8.0. The HA
configuration check is valid; template, resource, and theme reloads completed
without a restart. No physical actions were invoked during verification.

Browser smoke checks cover phone (390px), tablet (768px), Split View (600px), and
desktop (1280px), with light/dark appearances and native keyboard focus. Native
room tiles and primary tabs replace inaccessible custom-card navigation paths.
The new primary views pass the dashboard designer validator with zero errors;
its warnings identify the native cards deliberately selected for this design.

Physical iPhone/iPad rotations, OS text enlargement, camera streaming over the
remote connection, and a real trip/return cycle remain soak checks. A synthetic
fixture is not proof of physical cleaning or feeding. Current integrations do
not expose dependable secondary-robot completion or fresh feeder dispensing
reports, so these remain unverified. Do not promote develop to main until the
owner has completed the device and travel soak.

For the visual follow-up, compare actual HA screenshots with the original
examples at equivalent dimensions and appearances. The browser viewport override
did not take effect during this pass; a temporary same-origin iframe harness
provides genuine 390/600/768/1280px HA document widths instead. Record those checks
as browser frame tests, not physical-device verification. Remove the temporary
static harness after QA. Keep full screenshots and runtime exports private. The temporary iframe harness records one generic MutationObserver error; direct Home and Travel loads show no new console errors. Do not attribute the frame-only error to a dashboard card without reproducing it outside the harness.
