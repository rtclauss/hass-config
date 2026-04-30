# AGENTS.md

## Branching
- `main` is stable/live.
- `develop` is the HA test branch.
- Start every Codex worktree and feature branch from `origin/develop`; never branch from `main`.
- Feature/fix PRs must explicitly target `develop`; never rely on the repo default branch.
- `main` only accepts promotion PRs from `develop`.
- Do not push directly to `main`.
- After HA soak testing, promote with a PR from `develop` to `main`.
- Run `uv run --with pytest pytest` before PRs and merges.

## Reviews
- Audit GraphQL `reviewThreads` before merge.
- Treat `chatgpt-codex-connector` and `chatgpt-codex-connector[bot]` as the same reviewer.
- Classify each unresolved Codex comment as fixed, declined, or follow-up required.
- If fixed elsewhere, open a linked issue/PR and reference the source PR/comment.
- Re-check unresolved Codex threads after merge.

## Room Intent
- Use `docs/room_intent.yaml` as the source of truth for room purpose, guest privacy, and room-sensitive automation behavior.
- Read it before changing guest mode, occupancy, lighting, media, vacuum, climate, dashboards, or other room-targeted logic.
- If convenience behavior conflicts with room intent, preserve privacy-first behavior.

## Behavioral Specs
- Use `specs/alarm_wakeup.allium` as the source of truth for alarm, wake-up, snooze, and morning audio behavior.
- Use `specs/night_routines.allium` as the source of truth for bedtime preparation and overnight goodnight behavior.
- Before changing related Home Assistant automations, scripts, helpers, dashboards, or tests, read the relevant Allium spec first and keep implementation changes aligned with it.

## E-Ink Displays
- Use `docs/inky_displays.md` as the source of truth before changing e-ink payloads, renderer behavior, MQTT topics, Pi service deployment, display layouts, or display-triggering automations.
- The owner-suite display is a Pimoroni Inky wHAT red/black/white `400x300` panel on a Raspberry Pi Zero W. It reports as `Red wHAT (SSD1683)` and must use `INKY_PANEL_TYPE=auto`; do not force the legacy `what` driver for this board.
- Home Assistant owns desired state and publishes compact retained MQTT payloads. The Pi service owns rendering, duplicate suppression, local cache restore, and physical refresh.
- Current owner-suite command topic is `home/inky/owner_suite/state`. Keep future health/status topics separate from desired-state topics.
- E-ink updates are expensive whole-panel refreshes. Do not add `sensor.time`, minute-level clock ticks, animation, or cosmetic-only refresh triggers. The footer update time must reflect the payload publish time, not drive periodic redraws.
- New display content should be distance-legible: high-contrast `400x300`, one large title, one subtitle, at most four rows, Material Design Icons names where possible, and no dense dashboard-style text.
- Preserve color semantics: red means urgent/exception on the owner-suite board; yellow means emphasis/hospitality on the future office board.
- Test renderer changes with `python3 -m pytest tests/test_inky_display_renderer.py tests/test_inky_display_service.py tests/test_inky_displays_package.py`. For physical changes, verify on the Pi Zero W and confirm the panel visibly changes, not just that `show()` returns.

## Local Runtime Targets
- Keep machine-local runtime verification targets in `AGENTS.local.md`.
- Do not commit `AGENTS.local.md` unless explicitly asked.
