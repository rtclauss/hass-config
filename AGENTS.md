# AGENTS.md

## Room Intent
- Use `docs/room_intent.yaml` as the source of truth for room purpose, guest privacy, and room-sensitive automation behavior.
- Read it before changing guest mode, occupancy, lighting, media, vacuum, climate, dashboards, or other room-targeted logic.
- If convenience behavior conflicts with room intent, preserve privacy-first behavior.

## Local Runtime Targets
- Keep machine-local runtime verification targets in `AGENTS.local.md`.
- Do not commit `AGENTS.local.md` unless explicitly asked.
