# Promotion audit (develop → main)

`develop` is the HA test branch and `main` is stable/live. Promotions used to be
rare and large (main went from 2026-04-07 to 2026-10-08 without one), so a weekly
audit now reports what is ready to move.

## What runs

- `.github/workflows/promotion-audit.yml` runs every Monday (and on demand via
  *Run workflow*, with an optional `days` input).
- It runs `scripts/promotion_audit.py` against `origin/develop` and `origin/main`,
  then creates or updates the single open issue labelled `promotion-audit`.
- It is report-only. It never opens a PR, pushes a branch, or touches `main`.
- The promotable file list is also uploaded as the `promotion-audit-files` artifact
  (`status<TAB>path` per line).

Run it locally with:

```bash
git fetch origin
python3 scripts/promotion_audit.py --output /tmp/audit.md --files-out /tmp/files.txt
```

## The rule

A file is **promotable** only if everything it was ever changed together with (the
same first-parent change on `develop`: squash commit, PR merge, or direct commit)
has also been quiet for N days (default 30). That stops half of a feature reaching
`main`.

- `custom_components/<name>` is judged as one unit and is never linked to other files.
  Its consumers are covered by the exclusions file instead.
- `README.md`, `AGENTS.md`, `.gitignore`, `inventory.md` and `.github/**` are touched by
  almost every PR, so they do not link changes together and are never promoted by
  the audit.
- Changes touching 20+ files (sweeps such as the trace-retention change) are ignored
  when linking.
- Files matching `docs/promotion_audit_exclusions.yaml` count as recently changed, so they
  hold back everything tied to them. Use it for deliberate holds (features reverted off
  `main`, temporary diagnostics, atomic renames). Delete a line once its reason is gone.

## Reading the report

- **Promotable now** are *candidates*, not a guarantee. Some tests read shared files
  such as `README.md`, and runtime dependencies are not visible to git. Build a branch off
  `main`, copy the files from `develop`, and run `uv run --with pytest pytest` plus the HA
  config check before opening the promotion PR.
- **Quiet but entangled** changes are old but share files with code that is still changing.
  The "What is blocking the rest" table names the recently changed files holding them up.
- **Still soaking** changes touch files changed within the threshold.

## Merging a promotion

`.github/workflows/enforce-main-promotion.yml` requires PRs into `main` to come from
`develop`. A partial promotion comes from a `promote/*` branch, so that check fails and
needs a manual override. See #1089 / #1090 for the first one.
