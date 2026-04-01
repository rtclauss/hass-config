# Trace Sweep Playbook

Use this reference when the task is to review many traces rather than debug a single named automation or script.

## Candidate Selection

Build a bounded candidate set instead of scanning the entire system blindly.

Prefer this order:

1. entities named in the issue or repair
2. entities mentioned in recent errors, persistent notifications, or open runtime issues
3. enabled automations/scripts in the affected package or area

Use `ha_search_entities(query="", domain_filter="automation")` and `ha_search_entities(query="", domain_filter="script")` to enumerate candidates when the issue is broad.

## Trace Classification

For each candidate:

1. call `ha_get_automation_traces(..., limit=10)`
2. group runs into:
   - completed as expected
   - benign `failed_conditions`
   - benign one-off `failed_single`
   - repeated overlap that changes behavior
   - runtime faults
3. fetch detailed traces only for suspicious runs

Do not create work for harmless guard-condition failures.

## GitHub Triage Loop

For each confirmed defect:

1. look for an existing open issue first
2. check whether an open PR already references it
3. if no issue exists, open or update one with:
   - affected entity
   - short trace summary
   - minimal fix hypothesis
   - verification needed
4. if the defect is implementable now, prepare a branch from `origin/develop`, add tests, and open a PR targeting `develop`

When a defect is blocked by missing credentials, hardware access, or unsafe ambiguity, leave the issue with a concise blocker note rather than guessing.

## Fix Scope Guardrails

Preserve the automation's existing job unless the trace proves the job itself is wrong.

Prefer:

- stale entity fixes
- explicit availability guards
- narrower triggers
- shorter waits or corrected mode only when traces show missed behavior

Avoid:

- policy changes without room-intent review
- broad refactors unrelated to the failing path
- opening one giant PR for unrelated trace bugs

## Verification Checklist

Before you call the work done:

- touched tests pass
- `uv run --with pytest pytest` passes
- touched Home Assistant YAML, if any, passes the repo validation path
- the issue or PR summary distinguishes confirmed bugs from benign traces
