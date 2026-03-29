# AGENTS.md

## Branching
- `main` is stable/live.
- `develop` is the HA test branch.
- Start local work in a worktree from `origin/develop`.
- Feature/fix PRs target `develop`.
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

## Local Runtime Targets
- Keep machine-local runtime verification targets in `AGENTS.local.md`.
- Do not commit `AGENTS.local.md` unless explicitly asked.
