# Notification audit

Owner policy: **Only notify when a task needs attention; add useful buttons and
links.** Prioritize the task, its urgency, and whether the owner can act now.
Buttons support that decision; they do not turn routine status into a task.

This audit covers the owner's installation. The parents' installation is deferred
at the owner's request. It supports [routing issue #107](https://github.com/rtclauss/hass-config/issues/107).

## Evidence and limits

The live package files and UI automations contain 110 automation/script source
definitions with notification or notification-cleanup calls, including three
Live Activity definitions present in both package and UI sources. They contain
184 visible notification branches; 22 already declared buttons before this change. These are source
counts, not unique active automations or measured notification deliveries.
AppDaemon stall monitors and the RTL-SDR watchdog were also inspected. Integration
notifications were sampled from Home Assistant's active persistent notices.
Vendored integration code was not reviewed.

The snapshot contained 14 persistent notices, including four blind diagnostics,
several vacuum maintenance notices, a vacuum completion notice, overlapping
battery notices, and an arrival-audio failure. Counts change with runtime state.
This does not measure phone notification frequency or establish the provenance of
every historical notification. Definition-only findings below are distinguished
from observed runtime findings.

## Attention order

| Order | Task class | Send when | Delivery |
| --- | --- | --- | --- |
| 1 | Immediate safety or security | A verified active hazard requires action now | Immediate push with clear instruction and relevant controls; critical delivery only for the appropriate hazard |
| 2 | Important unresolved exception | Automatic recovery failed, security/readiness is not verified, or important monitoring is lost | One incident notification with the failed requirement and next step |
| 3 | Household task or explicit decision | A real task remains and this is a useful time to act | One task notification, useful controls, and bounded reminders |
| 4 | Useful context | No task currently needs attention | Dashboard or silent ongoing activity when useful; no interrupting push |
| 5 | Debug or successful internal operation | No owner decision is needed | Logs and traces; temporary diagnostics must expire or be explicitly enabled |

Recovery updates should close or silently update the original incident. A new
affected device can be a new task; a changed number, percentage, or wording is not.
One incident should not generate independent phone, laptop, TV, and speech alerts
unless the urgency justifies each channel. Notification clear commands are
transport housekeeping, not debug alerts to remove.

## Prioritized tasks

| Notification family and source | Classification | When it merits attention | Existing affordance / gap |
| --- | --- | --- | --- |
| Tornado warning (`weather`) | 1 | Active relevant warning | Already has critical sound and shelter instruction; preserve it |
| Wet floor (`alerts`) | 1 | Active leak | Add water controls and sensor details; dry/recovered is a local incident update |
| Sump getting full / full (`utilities`) | 1 | Valid high-water reading | Add pump/level links; fix missing monitoring before claiming coverage |
| Away activity / triggered alarm (`alerts`) | 1 | Armed-away security incident | Add alarm controls; consolidate the activity/alarm/camera copies into one incident later |
| Garage left open (`car`, `trips`) | 2, potentially 1 by context | Door remains open when it should be secured | Trip flow already offers Close / Ignore; ordinary reminder needs garage controls |
| Departure / goodnight integrity (`zone`, `house_mode`) | 2 | A requirement is still wrong after verification/retry | Real exceptions already consolidated; needs links to the specific failed controls |
| Guest visit NOT ready / NOT secured (`trips`) | 2 | Alarm, water, privacy, or docking requirement actually failed | Keep the failed requirements explicit; add relevant controls in a later targeted change |
| Persistent Zigbee lifecycle or systemic failure (`z2m_lifecycle`) | 2 | Device function is unavailable after appropriate recovery, especially security/water sensors | Prefer one grouped incident; recovery progress is lower priority |
| Sonos still unavailable after recovery (`media_player`) | 2 or 3 | A needed room remains unusable | Message already gives physical power-cycle instructions; add room/device link |
| Wake audio completely failed (`media_player`) | 2 | Both sources failed for an expected wake | Currently local only; promote a real failure to a task alert; successful fallback stays local |
| Tesla departure not armed (`car`) | 2 | An upcoming needed departure still lacks its schedule | Currently local only; use departure context and vehicle link, not every planner update |
| Water-meter reader still failing (`water_meter`) | 2 or 3 | Sustained reader failure needs intervention | Existing failure push lacks a useful destination; recovery should update the incident |
| Domain expiry (`domain_name`) | 2 or 3 | Renewal needs action before expiry | Link to the relevant renewal information; avoid repeating daily when already acknowledged |
| Energy anomaly (`utilities`) | 2 or 3 | Unexpected load persists and needs investigation | Identify likely load / link to energy; normal automatic loads must not produce tasks |
| Battery below 10% (`batteries`) | 3, higher for a critical sensor | A device needs charging or replacement | Newly affected devices only; add details button; distinguish a phone from a replaceable battery |
| Battery reading unavailable (`batteries`) | 2 or 3 by device function | A sustained outage needs investigation | Unavailable does not prove dead battery; group correlated outages and provide device details |
| Washer waiting / musty, dryer waiting (`cleaning`) | 3 | Load still needs unloading and owner can act | Add status links; retain actual door/state completion detection, not a pretend Done button |
| Delivered mail/packages (`mail_packages`) | 3 | Delivery remains uncollected and owner can retrieve it | Already has Retrieved / Still outside; avoid duplicate mailbox/tracker notices and reminders while away |
| Garbage / changed pickup (`utilities`) | 3 | Bins need setting out or the schedule changes tonight's task | Keep the task-specific reminder; later add completion tracking if a reliable signal is available |
| Salt low / forecast low (`water_softener`) | 3 | Refill is actually due, or purchase opportunity is useful | Existing cleaning link; add level button; merge forecast and actual-low into one task lifecycle |
| Salt / filter shopping (`water_softener`, `climate`) | 3 | Stock is low at a useful shopping opportunity | Existing text-input purchase buttons; keep once per errand and suppress if no purchase is needed |
| Diffuser oils (`diffusers`) | 3 | Six-month task is due and not already completed | Already has Replaced and one-cycle latch; preserve approved spec |
| Plants (`plants`) | 3 | A specific treatable moisture/temperature problem remains | Existing plants link; distinguish sensor outage from a plant-care instruction |
| Mouse caught (`mouse_trap`) | 3 | Trap needs checking/emptying | Reset counter is not the same task; provide trap/counter details and separate emptying from lifetime count |
| Tire rotation (`car`) | 3 | Rotation is actually due | Add mileage/service information and completion state in a follow-up |
| 3D print complete (`octoprint`) | 3 or 4 | Print is ready for collection and owner can act | Add printer link; do not repeat normal completion as a fault |
| Vacuum stalled (`AppDaemon`) | 3 | Robot needs physical help | Already has image/dashboard link; prioritize this over automatic retries and guest-veto skips |
| Vacuum map decision / failed apply (`vacuum_map_guard`) | 3 | Owner choice is required or automatic keep failed | Already has Accept / Keep; add robot destination for a failed apply |
| Vacuum MQTT reload / CleanGenius restore exhausted (`zigbee_zwave`, `xiaomi_robot_vacuum`) | 3 | Repair remains necessary before next needed run | Currently local notices; link to robot/integration and notify once if intervention is needed |
| Guest mode / startup trip confirmation (`guest`, `trips`) | 3 | Context is genuinely ambiguous and a decision is pending | Existing Yes/No and Enable/Disable buttons; remove prompts once context is resolved |
| Windows open / climate paused (`climate`) | 3 | Open windows conflict with active climate, or climate needs resuming | Existing Pause/Resume/Ignore controls; respect Ignore/Keep paused and suppress irrelevant follow-ups |
| Open windows with imminent rain (`weather`) | 2 or 3 | A window is actually open and rain matters now | Add open-window details; merge pressure/forecast/departure signals into one incident |
| General weather / legacy NWS push (`weather`) | 2, 3, or 4 by event | A relevant alert requires a specific protective task | Dedicated tornado path exists; generic and legacy paths still need event-ID/severity deduplication |
| Z2M device removal results (`z2m_lifecycle`) | 3 for requested operation | Removal failed, or inventory reconciliation is pending | Link to the administrative task; ordinary removal progress stays local |
| Unexpected authentication failures (HA integration notice) | 2 if repeated/unrecognized | Access investigation is needed | A single stale client's failure is troubleshooting context; do not treat all failures alike |
| Vacuum maintenance (integration notices) | 3 | Brush/filter replacement or sensor cleaning is due | Real tasks; consolidate one maintenance list and link to the actual counter reset after physical work |

## Action-capable notifications with no task right now

Existing buttons should not create a reason to interrupt. Suppress the prompt
when its condition is false or already handled:

- Mail/packages retrieved, washer emptied, dryer cleared: resolve the task.
- Climate already appropriate, windows closed, or Keep paused chosen: no repeat decision.
- Guest/trip context confidently correct: no confirmation just because HA restarted.
- Salt forecast far from low with no useful purchase opportunity: no refill task yet.
- A robot intentionally skipped for guest privacy, owner arrival, an existing
  manual run, or an expired queue entry: expected policy, not a repair task.
- A pre-arrival clean is retrying automatically: status while recovery is in
  progress; notify when it cannot meet a real readiness requirement.
- Preconditioning/planned charging is healthy: show the plan; push only the exception.
- Car windows are being closed successfully by the automation: no task unless
  closure fails verification.
- A wake-audio fallback succeeded: degraded-source diagnostic, not failed wake audio.

## Debug and optional information to quiet

| Source | Examples | Disposition |
| --- | --- | --- |
| `blind_forensics` | Blind movement context IDs, positions, per-context persistent notices | Debug; keep logs/traces, stop accumulating user notices. Runtime watcher is enabled |
| `media_player` | Playlist selection pushes the internal `script.bedroom_playlist_*` name | Debug; log the selection. Runtime automation is enabled |
| `water_softener` | `temp_notify_place_name` place/category dump | Debug; its only trigger is already disabled even though the automation entity is on |
| `parasoll_fix` | Reconfiguring, applied, configure queued | Debug/progress; only a sustained configuration failure needs a task |
| `trips`, `holidays` | Vacation light group, lights on/off, Christmas tree on/off | Routine success; log/dashboard only |
| `zone`, `workday`, `curling`, `trips` | Welcome Home, Good Curling, Bedroom Prep Activated, automatically setting Ecobee Home/Away | Routine success; log/dashboard only |
| `trips`, `guest` | Trip enabled/disabled, guest mode deactivated, guest visit house-ready/secured | Successful state transitions; keep only the pending decision or failure alert |
| `fans` | Vacancy failsafe successfully turned the ceiling light off | Successful self-repair; log unless verification fails |
| `diffusers`, `mouse_trap` | Oils marked replaced, counter reset | Acknowledgement; update/clear the original task instead of sending a fresh push |
| `utilities` | Sump run totals, weekly energy cost | Useful report, no current task; local notice in first implementation |
| `water_meter`, `z2m_lifecycle` | Recovered, restarting, OTA still running | Recovery/progress; silently update incident except consequential failed recovery |
| `AppDaemon RTL-SDR watchdog` | `[DRY RUN]` staged restart/shutdown descriptions | Rollout diagnostic. Current docs require every-stage observation; preserve dry-run safety and revise rollout policy explicitly before quieting it |
| `utilities` | Generic stale-entity list | Diagnostic until actual loss of required function is established; unchanged state alone is not failed reporting |
| `camera`, `alerts` | Pet spotted, motion snapshot | Optional activity; relevant armed-away security evidence belongs on the existing incident; preserve guest privacy |
| `cleaning`, UI Live Activities | Cleaning/progress/phase/completed updates | Silent ongoing activity only; exception requiring help is a separate task |
| `alerts` | Shared-notification TV mirror | Amplification, not a new task; restrict to selected urgent incidents in routing work |
| `house_mode` | Generic caller-provided transition message | Classify the caller's task; normal transitions should not inject success pushes |
| `z2m_lifecycle` | Decommission requested / select a device | Local feedback for an explicit administrative operation, not a broadcast |

## Runtime findings to address first

1. **Lost sump monitoring:** `sensor.sump_fill` was unavailable. Both high-water
   automations depend on it. Enabled automations do not establish working coverage.
2. **Correlated battery-device outage:** roughly two dozen battery readings were
   unavailable during the snapshot, with no available sibling states found in
   that sample. Investigate common availability/network causes before asking for
   dozens of battery replacements. The count changed during the review.
3. **Duplicate battery attention:** below-20%, below-10%, and Battery Sentinel
   all described overlapping devices. One low reading was a rechargeable phone;
   another was a replaceable-battery sensor. Consolidate task ownership and make
   the requested physical action accurate.
4. **Task-free persistent clutter:** blind diagnostics and vacuum completion were
   present alongside real maintenance work. Separate these from the maintenance
   list so the necessary work remains visible.
5. **Misleading existing button:** Z2M's button titled "Z2M failed" handles
   `REBOOT_Z2M_COUNTER`, which resets a recovery counter. It is not a cancel-host-
   restart action. Rename it to its actual effect before presenting it as a fix.

## Current task relevance at the audit snapshot

| Reported state | Attention now |
| --- | --- |
| Sump-level source unavailable | Restore or deliberately replace monitoring; this is a coverage gap |
| Roughly two dozen battery devices unavailable | Investigate the correlated outage; do not prescribe battery replacement from availability alone |
| Low-battery list includes a sensor at 0% and a phone at 5% | Check/replace the sensor battery and charge the phone; do not duplicate the same work in three channels |
| Dryer helper reports CLEAN; washer reports IDLE | Check/unload the dryer if the load is present; no washer task is currently reported |
| Garage reports closed; open-window aggregate reports off | No open-door/window task is currently reported; unavailable contacts still limit confidence |
| Softener forecast roughly three months away; spare-bag helper is zero | No immediate refill task; buying stock is useful at the next appropriate errand |
| Water reader reports OK; robot reports no error | No reader-repair or robot-error task is currently reported |

These are reported states at one point in time, not verified physical outcomes or
permanent facts. They must not become hardcoded notification suppressions.

## Implementation boundary

The first reduction and added navigation controls are recorded in
[notification_policy.md](notification_policy.md). Other classifications here are
recommendations, not claims that all producers have been changed. In particular,
critical severity routing, quiet hours, per-task acknowledgement, cross-source
deduplication, critical-sensor health monitoring, and the parents' installation
remain separate work. No behavioral Allium specs are changed by this audit.
