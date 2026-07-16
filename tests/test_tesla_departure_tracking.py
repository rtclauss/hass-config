"""The HA-managed Tesla departure must stay tracked until it is really cleared.

script.tesla_set_precondition_schedule_time refuses to send
`SCHEDULED_DEPARTURE enable:false` at a protected location while the Tesla app's
own scheduled/off-peak charging is active. Callers that dropped
input_boolean.tesla_managed_departure_active / input_number
.tesla_managed_departure_ts regardless left the preconditioning schedule armed
on the car with nothing on the HA side left to retry it.
"""

from __future__ import annotations

import re
from pathlib import Path

CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"

# Automations that ask the script to disable the schedule and then decide
# whether to stop tracking it.
DISABLE_CALLERS = (
    "tesla_departure_planner_apply",
    "tesla_departure_cancel_when_home_context_ends",
    "tesla_departure_schedule_cleanup",
)


def _text() -> str:
    return CAR_PATH.read_text(encoding="utf-8")


def _automation_block(automation_id: str) -> str:
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(_text())
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def _script_block(script_id: str) -> str:
    pattern = re.compile(
        rf"^  {re.escape(script_id)}:\n(.*?)(?=^  [A-Za-z0-9_]+:\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(_text())
    if match is None:
        raise AssertionError(f"Could not find script block {script_id!r}")
    return match.group(0)


def test_script_reports_whether_it_cleared_the_tesla_schedule() -> None:
    block = _script_block("tesla_set_precondition_schedule_time")

    assert "response_variable: tesla_schedule_result" in block
    assert "- stop:" in block
    # The result must be derived from the same guard that decides the API call,
    # so the two can never disagree.
    assert "cleared:" in block
    assert "safe_to_clear_tesla_schedule" in block


def test_script_result_is_computed_at_the_top_sequence_level() -> None:
    # A value set inside a choose/then sub-script is not visible to a later
    # top-level step, so the result variable must be a top-level step.
    block = _script_block("tesla_set_precondition_schedule_time")
    lines = block.splitlines()

    stop_lines = [line for line in lines if line.strip().startswith("- stop:")]
    assert stop_lines, "script never returns a response"
    for line in stop_lines:
        assert line.startswith("      - stop:"), f"stop is not a top-level step: {line!r}"


def test_every_disable_caller_gates_untracking_on_the_script_response() -> None:
    for automation_id in DISABLE_CALLERS:
        block = _automation_block(automation_id)
        assert "enabled: false" in block, f"{automation_id}: not a disable caller"
        assert "response_variable: tesla_schedule_result" in block, (
            f"{automation_id}: ignores whether the Tesla schedule was cleared"
        )
        assert "tesla_schedule_result.cleared" in block, (
            f"{automation_id}: does not check the cleared result"
        )


def test_untracking_never_happens_unconditionally_after_a_disable_call() -> None:
    # The helpers may only be reset inside the `then:` of the cleared check —
    # never as a bare step following the script call.
    for automation_id in DISABLE_CALLERS:
        block = _automation_block(automation_id)
        lines = block.splitlines()

        for index, line in enumerate(lines):
            if "entity_id: input_boolean.tesla_managed_departure_active" not in line:
                continue
            if "turn_off" not in "\n".join(lines[max(0, index - 3):index]):
                continue
            preceding = "\n".join(lines[:index])
            assert "tesla_schedule_result.cleared" in preceding, (
                f"{automation_id}: clears tracking without checking the result"
            )


def test_cleared_result_defaults_to_false_when_the_script_returns_nothing() -> None:
    # mode: restart — a concurrent call cancels the first run and its caller gets
    # an empty response. Defaulting to false keeps the departure tracked, which
    # is the safe direction (retry later rather than strand an armed schedule).
    for automation_id in DISABLE_CALLERS:
        block = _automation_block(automation_id)
        assert "tesla_schedule_result.cleared | default(false)" in block, (
            f"{automation_id}: an empty script response would raise or misread"
        )


def test_away_cancel_retries_when_tesla_schedule_timestamp_catches_up() -> None:
    block = _automation_block("tesla_departure_cancel_when_home_context_ends")

    assert "entity_id: binary_sensor.nigori_scheduled_departure" in block
    assert "attribute: Departure timestamp" in block
    assert "id: tesla_schedule_synced" in block
    assert "not is_state('person.ryan', 'home')" in block
    assert "not is_state('device_tracker.nigori_location_tracker', 'home')" in block
    assert "force_disable: true" in block
