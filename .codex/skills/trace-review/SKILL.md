---
name: trace-review
description: Review Home Assistant automation, scene, and script traces; separate benign runs from real faults; and turn confirmed defects into the smallest validated fix or PR-ready issue update.
---

# Trace Review

Use this skill when a task involves Home Assistant traces, runtime failures, noisy automations, or issue sweeps such as repo issues `#314` and `#316`.

## Modes

Choose one mode before you start:

- `Issue mode`: investigate a specific automation, script, or scene named in an issue or repair.
- `Sweep mode`: review a bounded set of live automation/script/scene traces, classify the failures, and turn confirmed defects into issue or PR work without rewriting healthy logic.

Read `references/sweep-playbook.md` when you need the full sweep procedure or GitHub triage loop.

## Workflow

1. Orient on the live system first.
   Use:
   - `ha_get_overview(detail_level="minimal", include_entity_id=True)`
   - `ha_search_entities(query="", domain_filter="automation")`
   - `ha_search_entities(query="", domain_filter="script")`
   - `ha_search_entities(query="", domain_filter="scene")`

2. Pull the current config before judging a trace.
   Use:
   - `ha_config_get_automation`
   - `ha_config_get_script`
   - `ha_deep_search` for referenced helpers, scripts, dashboards, and consumers

3. Pull recent traces, then drill into suspicious runs.
   Use `ha_get_automation_traces(<entity_id>, limit=10)` first.
   Fetch detailed evidence with `ha_get_automation_traces(..., run_id=<id>, detailed=True)`.

4. Separate noise from defects.
   Treat these as normally benign unless they violate the intent:
   - `failed_conditions` where the guard correctly blocked execution
   - one-off `failed_single` runs caused by overlapping equivalent triggers

   Treat these as real bugs:
   - stale or unavailable entity references
   - action/service-call errors
   - repeated overlap that suppresses materially different runs
   - logic that contradicts room policy or package intent

5. Preserve room policy before changing room-targeted logic.
   Read `docs/room_intent.yaml` before changing occupancy, lighting, media, vacuum, climate, dashboards, or guest-sensitive automations.

6. Correlate the finding with GitHub before editing.
   Prefer updating an existing issue. Search for a linked open PR before starting new implementation work.
   If the bug is new, open or update the issue with the trace evidence, affected entity, and minimal proposed fix.

7. Make the smallest safe change.
   Prefer:
   - fixing stale entity references
   - tightening triggers or guards
   - removing noisy duplicate paths
   - adding explicit protection for unavailable entities

   Avoid:
   - rewriting the automation because a newer pattern exists
   - changing the core intent when the trace only shows a benign blocked run

8. Add or update tests for every accepted fix.
   Cover:
   - the entity IDs or services involved
   - the trigger or condition path you changed
   - the regression exposed by the trace

9. Validate before proposing a PR.
   Run targeted tests first, then `uv run --with pytest pytest` when the repo change is ready.
   If you touched Home Assistant YAML, also run the repo's relevant config validation and any touched-file linting.

## Review Output

When you report results, separate them into:

- `Confirmed bug`
- `Benign trace`
- `Needs runtime verification`

For each confirmed bug, include:

- affected entity
- triggering trace pattern
- live state or device evidence
- why the current logic is wrong
- the minimal fix
- the test that proves it
- whether there is already an issue or PR for the defect
