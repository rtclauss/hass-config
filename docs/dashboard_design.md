# Dashboard design guide for future agents

Living design brief established 2026-11-02. Read this before dashboard work and
keep it current as the owner gives feedback and the implementation is verified.
This guide records decisions and their supporting reasons; it is not a transcript
or a substitute for checking the current configuration.

## Reusable agent instruction

> Continue the Calm contextual Home Assistant dashboard. Preserve its minimalist,
> rooms-first vocabulary and familiar navigation across macOS, iPadOS, and iOS.
> Use grouped controls, progressive disclosure, and one contextual section to
> make the appropriate information available at the appropriate time. Keep
> frequent controls in stable locations. Prefer native, UI-editable Lovelace
> components; use selected HACS components when they meet a demonstrated need.
> Make status truthful: distinguish reported state, activity, and verified
> completion, and expose meaningful exceptions without depending on context.
> Respect room privacy and existing automation policies. Read the linked policy
> and implementation documents, inspect live capabilities and relevant history,
> validate touch and keyboard access in both appearances, and update this guide
> with new decisions and evidence in the same change. Identify unverified
> assumptions and remaining device checks explicitly.

## Owner-approved brief

- **Calm and clear:** a minimalist interface with readable labels, neutral
  surfaces, restrained state colors, and little visual noise.
- **Match the renders:** owner feedback on 2026-11-02 established that the first
  implementation did not resemble the examples closely enough. Their hierarchy,
  two-column room composition, spacing, and compact panels are visual acceptance
  criteria. Functional parity alone is insufficient; sample entity values remain
  illustrative and must never become fabricated live status.
- **Rooms first:** work with groups of items, then open room details for
  individual devices. Also provide whole-house lighting, climate, media, and
  household tasks.
- **Frequent travel:** remotely check security, cameras, pet care, temperature,
  and water. On departure and return days, surface preparation and actual
  readiness, including vacuuming and mopping.
- **Appropriate context:** change emphasis at the right time while keeping every
  destination manually accessible and important controls predictable.
- **Platform parity:** support macOS, iPadOS, and iOS, including tablet Split
  View, portrait/landscape layouts, touch, and keyboard use where applicable.
- **Both appearances:** system-following light/dark mode with a manual override.
- **Practical implementation:** retain storage-mode Lovelace, UI editing, the
  existing daily dashboard URL, specialist capabilities, and existing links.
  Native buttons/controls and pre-built HACS items are acceptable.
- **Behavior boundary:** this rebuild changes presentation and observational
  reporting. Departure, return, water, climate, cleaning, alarm, and privacy
  policies keep their behavior unless the owner separately authorizes a change.

These are explicit preferences from the design conversation. Do not infer a new
owner preference from a skill's example, a fashionable dashboard, or an agent's
implementation choice.

## Design vocabulary

| Term | Meaning in this dashboard |
| --- | --- |
| Calm | Stable placement, restrained decoration, and limited competing emphasis. |
| Clear | Name the item, its actual state, and the useful next step in plain language. Never rely on color alone. |
| Group | An existing meaningful room/device group, shown before its individual members. A group summary must not imply that every member has the same state. |
| Progressive disclosure | Show the useful summary first; open detail views, cameras, maps, graphs, and specialist controls when requested. |
| Context | An explanation of what matters now, derived from existing household signals. It does not grant permission to operate devices. |
| Stable anchors | Navigation, favorites, and room order that stay in the same places when context changes. |
| Exception | A condition that merits attention, including unavailable critical security/water monitoring. Exceptions remain visible independently of the contextual presentation. |
| Readiness | Evidence about a particular requirement for the associated return cycle, with a status, reason, source, and evidence timestamp. |
| Reported state | What an integration/device reports. It may not prove the physical outcome. |
| Activity | A start, running state, launch attempt, or other progress signal. Activity alone does not prove successful completion. |
| Completion | A trustworthy success result associated with the applicable cycle and evidence window. |
| Unknown / unverified | Evidence is missing, unavailable, stale for this cycle, or insufficient. This is useful information and must not silently become ready. |
| Blocked | A known obstacle or condition requiring attention; explain the cause. |
| Scheduled / running | The existing workflow is pending or active; neither means complete. |
| Skipped | An explicitly established omission. A missed deadline alone cannot distinguish skipped from interrupted or unreported work. |
| Landing | The flight's reported landing time in HA's timezone. It is not an estimate of arrival at the house. |

## Information architecture and prioritization

| Destination | Primary question |
| --- | --- |
| Home | What matters now, and where are my frequent controls? |
| Rooms | How do I control this room together and inspect its devices? |
| House | How do I manage lighting, comfort, media, and household tasks across rooms? |
| Travel | What is happening remotely, and what is actually ready for departure/return? |
| More | Where are the specialist dashboards and administration capabilities? |

The initial history-informed favorites prioritize bedroom audio, fan, lamps,
blinds, bathroom lighting, and alarm access. This is a design input from the
initial inspection, not a permanent frequency ranking. State churn and automation
activity are not equivalent to deliberate user interactions. For future history
analysis, record the observation window, attribution limitations, and resulting
decision without publishing personal histories or inventing interaction counts.
Change favorite order deliberately with owner feedback; do not automatically
reorder controls as usage or context changes.

Use the existing context rules for sleep, departure, away, return, evening,
morning, home, and unknown. The exact precedence and evidence contract live in
[the implementation guide](calm_dashboard.md#reporting-contract) and the shared
macros/tests. Future itineraries alone do not activate travel context. Guest
privacy and important exceptions remain applicable in every presentation.

## Visual and interaction language

- Use the **Calm Home** theme as the shared token source. It currently uses
  system typography, 16px card corners/section spacing, neutral light/dark
  surfaces, a muted green accent, and no card shadows. Consult
  [the theme](../themes/calm-home.yaml) for exact values instead of copying them
  into individual cards.
- Prefer native Sections for reflow and native Tiles/controls for familiar
  interaction and accessibility. Installed Mushroom Template cards provide richer
  room summaries using native Tile semantics. Use reusable composition functions
  and shared templates for consistency. Keep styling centralized and card-mod
  narrowly scoped to demonstrated needs.
- Home leads with the contextual header, status chips, and context panel, then a
  two-column room grid. Media and whole-house panels follow; compact quick
  controls and independently visible exceptions remain accessible. Do not let
  large sliders dominate the first screen again. Room cards use a 144px minimum
  height with left-aligned icons and text, soft surfaces, and no outline border.
- The theme owns visual tokens and shared card classes. Markdown typography uses
  one shared JSON style snippet in the composer because theme-YAML styling did
  not initialize in the tested client. Do not introduce per-instance variations.
- Keep labels visible and concise. Use text plus icons for status; reserve
  stronger emphasis for actionable exceptions. Do not add decorative motion,
  persistent camera feeds, wallpaper, blur, or dense telemetry to Home without
  a concrete user need and validation of its readability/performance cost.
- Important controls must work without hover, long-press, or color recognition.
  Check keyboard focus and activation, touch targets of at least 44px, text
  enlargement, safe areas, and the final scroll position above navigation.
- Follow the client's system appearance with **Calm Home → Auto** in its profile;
  Light/Dark are manual overrides. Selecting the theme per client is part of
  setup. Check appearance switching in the actual HA client.
- Show device-reported supply, climate targets/ranges and HVAC activity, and
  individual cleaning results accurately. Calm presentation must not conceal
  uncertainty or combine unresolved items into a reassuring "all ready" claim.

The owner's request to examine 2026 UI/UX informed the emphasis on responsive
native controls, restrained surfaces, and contextual disclosure. A year label is
not a reason to adopt a new visual effect or presentation layer. Future research
should use current primary documentation and distinguish inspiration from
capabilities verified on the installed stable HA/HACS releases.

## Decision rationale and implementation lessons

Established 2026-11-02; references: owner-approved plan, implementation and review
in [PR #1167](https://github.com/rtclauss/hass-config/pull/1167).

| ID | Decision and reason | Revisit when |
| --- | --- | --- |
| D01 | Keep storage-mode Lovelace. It preserves UI editing, HA integration, existing URLs, and a manageable maintenance burden. No separate frontend/view engine was needed for v1. | A concrete, tested requirement cannot be met within Lovelace. |
| D02 | Keep five stable destinations and one contextual section. This supports habitual control while changing emphasis for travel or sleep. | Owner feedback demonstrates a recurring navigation problem. |
| D03 | Show room groups first and keep specialist details reachable. This matches the owner's working style and avoids a device inventory on Home. | A group does not match actual room intent or hides necessary member differences. |
| D04 | Use Tile-derived room controls. The original custom button card lacked keyboard focus; plain native Tiles restored access but did not reproduce the renders. The visual pass uses installed Mushroom Template cards for richer summaries and native focus semantics. The whole card is the labelled action; decorative icons do not create duplicate unnamed controls. | A replacement demonstrates equivalent or better visual fidelity, touch, keyboard, and assistive access. |
| D05 | Use Navbar Card for labelled bottom navigation below 1200px and a side rail on wider screens, with safe-area handling and automatic padding. Retain native HA tabs that reveal on keyboard focus because the tested Navbar release lacked keyboard route semantics. | The dependency gains verified keyboard access or HA offers an equivalent native navigation option. |
| D06 | Centralize minimal accessibility styling. Live testing found 36px native tile icons and narrow fan speed buttons; shared 44px sizing and a full-row fan control corrected the new controls. | HA changes its component sizing/DOM or responsive testing finds another constraint. |
| D07 | Keep Home lightweight and load cameras on demand. This reduces visual load and avoids continuous media work during routine control. | A specific remote workflow needs a visible feed and its cost is measured. |
| D08 | Separate reporting from physical actions. A dashboard status must not change water timing, cleaning fallback, climate policy, or guest/pet protections. | The owner explicitly requests a separately reviewed behavior change. |
| D09 | Require cycle-associated success evidence. A dock, activity timestamp, retained MQTT message, feeder schedule, or launch marker cannot establish completion. Missing critical monitoring is visible on Home. | A device exposes trustworthy fresh result evidence and tests establish its semantics. |
| D10 | Derive reporting bounds from the selected landing and existing lead/buffer helpers. Review found that dependent timestamp sensors can briefly describe the previous flight, contaminating a newly saved cycle. Missing calibration leaves the window unknown. | The underlying travel contract changes; update race/restart/delay regression cases together. |
| D11 | Preserve restored evidence through restarts, delay, and arrival. An unavailable trip helper must not close the cycle; a new trip must not inherit previous results. | Verified source behavior or owner-approved travel policy changes require a different association. |
| D12 | Use native controls even where the dashboard-designer skill defaults to button-card. The owner explicitly approved this hybrid plan, and live accessibility findings support it. HTML examples establish the visual target; actual HA screenshots establish whether it was achieved. | Owner direction or verified component constraints change. |
| D13 | Treat visual fidelity as a separate acceptance check. The owner rejected the slider-led, four-across room composition as too different from the renders. Restore rooms first, two columns, compact panels, and the original spacing rhythm; compare actual HA views at equivalent sizes before declaring completion. | Owner feedback changes the target composition. |
| D14 | Keep styling centralized while avoiding a theme-YAML initialization failure observed during the visual pass. Shared theme CSS styles card classes; a shared JSON snippet styles Markdown. Navbar padding explicitly reserves the widened rail's space. | A dependency update is verified to remove the workaround, or card DOM/sizing changes. |

These are concise decision records, not universal rules about every HA dashboard.
Version-specific observations must be rechecked before carrying a workaround
forward. The installed versions and current soak record belong in
[calm_dashboard.md](calm_dashboard.md#deployment-and-soak-record).

## Instructions for each future change

1. Read this guide, [room intent](room_intent.yaml), the relevant behavioral
   specs, and the applicable HA skills. Owner instructions take precedence over
   generic skill styling preferences. The initial requested skills were
   `home-assistant-best-practices`, `homeassistant-dashboard-designer`, and
   `home-assistant`; resolve their current installed locations.
2. Inspect the relevant live states, actions, groups, resources, and history
   before assuming a capability or changing a control. Keep observations
   separate from inferred intent. State the user problem and the smallest useful
   presentation change, including its tradeoff and success criteria.
3. Preserve the storage dashboard and unrelated content. Follow the
   [export/apply/rollback procedure](calm_dashboard.md#export-apply-and-rollback),
   including private backups, a fresh configuration-hash check, and API readback.
   Never edit `.storage` directly. Store credentials, full runtime snapshots,
   personal mappings, and exact travel histories outside public Git.
4. Validate the relevant context/evidence transitions and live rendering. Recheck
   both appearances and phone/tablet/Split View/desktop sizes; do not substitute
   a mockup for HA verification or a browser viewport for a physical-device test.
   Separate automated test results, browser observations, and outstanding soak
   work. Do not mark completion from unsupported device evidence.
5. **Maintain this guide in the same change** when owner preferences, vocabulary,
   navigation, component strategy, evidence interpretation, or design lessons
   change. Update the current guidance rather than leaving contradictory text.
   Add or revise a dated decision record with the driver, supporting evidence,
   consequence, and condition for revisiting it. Label proposals and assumptions
   explicitly; record an owner approval only when it actually exists.
6. Update the implementation/soak guide for operational details and the PR for
   test/coverage evidence. Do not duplicate volatile test counts, runtime targets,
   or secrets here. If the design guidance still applies unchanged, say that in
   the PR rather than manufacturing a new preference or a cosmetic log entry.

This guide governs design intent. [Room intent](room_intent.yaml) governs privacy
and room purpose; [behavioral specs](../AGENTS.md#behavioral-specs) govern their
respective automations. Do not change an Allium definition without the owner's
explicit approval. A presentation improvement does not authorize a policy change.
