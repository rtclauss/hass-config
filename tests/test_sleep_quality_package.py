from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "sleep_quality.yaml"
DASHBOARD_PATH = ROOT / "lovelace" / "tiles" / "tiles_master_bedroom.yaml"


def _automation_block(automation_id: str) -> str:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def _script_block(script_id: str) -> str:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  {re.escape(script_id)}:\n(.*?)(?=^automation:)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find script block {script_id!r}")
    return match.group(0)


def test_sleep_session_uses_restorable_native_helpers() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    input_datetimes = text.split("input_datetime:", maxsplit=1)[1].split(
        "input_number:", maxsplit=1
    )[0]
    score_helper = text.split("  sleep_quality_score:", maxsplit=1)[1].split(
        "counter:", maxsplit=1
    )[0]

    for helper_id in (
        "sleep_session_bed_in",
        "sleep_session_cpap_on",
        "sleep_session_cpap_off",
        "sleep_session_bed_out",
    ):
        assert f"  {helper_id}:" in input_datetimes
    assert input_datetimes.count("has_date: true") == 4
    assert input_datetimes.count("has_time: true") == 4
    assert "restore: true" in text.split("counter:", maxsplit=1)[1].split(
        "script:", maxsplit=1
    )[0]
    assert "initial:" not in score_helper
    assert "\ntemplate:" not in text


def test_cpap_session_records_timestamps_and_counts_only_guarded_bed_transitions() -> None:
    prepare = _automation_block("sleep_quality_prepare_session")
    active = _automation_block("sleep_quality_track_active_session")

    assert "id: bed_entry" in prepare
    assert "id: cpap_start" in prepare
    assert "entity_id: sensor.owner_suite_cpap_plug_power" in prepare
    assert "above: 1.3" in prepare
    assert "seconds: 10" in prepare
    assert "entity_id: input_datetime.sleep_session_cpap_on" in prepare

    assert "binary_sensor.bed_presence_2d0670_bed_occupied_left" in active
    assert "binary_sensor.bed_presence_2d0670_bed_occupied_right" in active
    assert active.count("id: bed_transition") == 3
    assert 'from: "on"' in active
    assert 'to: "off"' in active
    assert 'from: "off"' in active
    assert 'to: "on"' in active
    assert "condition: numeric_state" in active
    assert "action: counter.increment" in active
    assert "entity_id: counter.sleep_restlessness_events" in active

    assert "id: cpap_stop" in active
    assert "below: 1.3" in active
    # cpap_stop's own for:, bed_exit's for:, and the ordering guard added
    # in the cpap_stop branch (test_cpap_stop_waits_for_beds_own_debounce_
    # before_finalizing) that mirrors bed_exit's debounce.
    assert active.count("minutes: 5") == 3
    assert "entity_id: input_datetime.sleep_session_cpap_off" in active
    assert "id: bed_exit" in active
    assert active.count("below: 1.3") == 2


def test_bed_exit_timestamp_is_persisted_before_later_session_finalization() -> None:
    active = _automation_block("sleep_quality_track_active_session")
    finalize = _script_block("finalize_sleep_quality_session")
    bed_exit_branch = active.split("id: bed_exit", maxsplit=2)[2]

    bed_out_write = bed_exit_branch.index(
        "entity_id: input_datetime.sleep_session_bed_out"
    )
    finalize_call = bed_exit_branch.index("action: script.finalize_sleep_quality_session")

    assert bed_out_write < finalize_call
    assert "state_attr('input_datetime.sleep_session_bed_out', 'timestamp')" in finalize
    assert "bed_out_ts >= bed_in_ts" in finalize
    assert "bed_out_ts >= cpap_off_ts" not in finalize
    assert 'bed_out_ts: "{{ now().timestamp() }}"' not in finalize


def test_finalize_always_clears_active_session_even_when_data_is_incomplete() -> None:
    # Codex P2 on #373: a hard `condition:` gate halted the whole script when
    # the session was incomplete/out-of-order (e.g. CPAP briefly used while
    # the aggregate bed sensor never registered occupied), so the trailing
    # input_boolean.turn_off never ran and sleep_session_active stayed
    # latched on, silently blocking every future session from starting.
    block = _script_block("finalize_sleep_quality_session")

    if_index = block.index("if:")
    then_index = block.index("then:", if_index)
    turn_off_index = block.index("action: input_boolean.turn_off")

    assert if_index < then_index < turn_off_index
    assert "condition: template" in block[if_index:then_index]
    assert "bed_out_ts >= bed_in_ts" in block[if_index:then_index]
    # The cleanup action must be a sibling of the if-block, not nested
    # inside `then`, so it always runs regardless of completeness.
    then_block_end = block.index("value: \"{{ continuity_score }}\"", then_index)
    assert turn_off_index > then_block_end


def test_cpap_off_and_bed_out_timestamp_the_actual_transition_not_the_delay() -> None:
    # Codex P2 on #373: now() inside these 5-minute-delayed (`for:`)
    # callbacks is ~5 minutes later than the real transition, so every
    # completed session over-reported cpap_minutes/bed_minutes by about 5
    # minutes each. trigger.to_state.last_changed is the actual transition
    # timestamp — but it's UTC (Codex P1 follow-up on #373): formatting it
    # directly gets interpreted as local time by input_datetime.set_datetime,
    # shifting every stored timestamp by the UTC offset. as_local() first is
    # required.
    active = _automation_block("sleep_quality_track_active_session")
    cpap_stop_branch = active.split("id: cpap_stop", maxsplit=2)[2]
    bed_exit_branch = active.split("id: bed_exit", maxsplit=2)[2]

    expected = (
        "datetime: \"{{ as_local(trigger.to_state.last_changed)"
        ".strftime('%Y-%m-%d %H:%M:%S') }}\""
    )
    assert expected in cpap_stop_branch
    assert expected in bed_exit_branch
    assert "datetime: \"{{ now().strftime('%Y-%m-%d %H:%M:%S') }}\"" not in cpap_stop_branch
    assert "datetime: \"{{ now().strftime('%Y-%m-%d %H:%M:%S') }}\"" not in bed_exit_branch
    assert "trigger.to_state.last_changed.strftime" not in cpap_stop_branch
    assert "trigger.to_state.last_changed.strftime" not in bed_exit_branch


def test_continuity_score_is_bounded_and_does_not_change_governed_routines() -> None:
    block = _script_block("finalize_sleep_quality_session")
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "cpap_points = [60" in block
    assert "bed_points = [40" in block
    assert "transition_penalty = [20" in block
    assert "[100, [0, cpap_points + bed_points - transition_penalty] | max] | min" in block
    assert "input_number.sleep_quality_score" in block
    assert "script.wake_up_script" not in text
    assert "script.goodnight_integrity" not in text
    assert "wakeup_alarm_firing" not in text


def test_cpap_stop_waits_for_beds_own_debounce_before_finalizing() -> None:
    # Codex P2 follow-up on #373: if CPAP drops first and the bed empties
    # during this branch's own 5-minute debounce, checking the bed's raw
    # current state let this fire before bed_exit had written bed_out,
    # finalizing on a stale/prior timestamp, rejecting the session, and
    # clearing sleep_session_active before bed_exit's own guarded call
    # could ever run — silently dropping a real completed session. Must
    # require the bed to have been sustained-off for 5 minutes too, same
    # as the bed_exit trigger's own debounce.
    active = _automation_block("sleep_quality_track_active_session")
    cpap_stop_branch = active.split("id: cpap_stop", maxsplit=2)[2]
    finalize_index = cpap_stop_branch.index("action: script.finalize_sleep_quality_session")
    preceding = cpap_stop_branch[:finalize_index]

    state_index = preceding.rindex(
        "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either"
    )
    guard_block = preceding[state_index:]
    assert 'state: "off"' in guard_block
    assert "minutes: 5" in guard_block


def test_restart_reconciles_a_lost_cpap_stop_debounce() -> None:
    # Codex P2 follow-up on #373: a pending numeric_state `for:` debounce is
    # discarded on an HA restart/reload, not resumed. If CPAP had already
    # dropped before the restart and the bed later empties,
    # sleep_session_cpap_stopped is stuck off, finalize is skipped, and
    # sleep_session_active latches on, blocking every future session.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert "entity_id: input_boolean.sleep_session_active" in block
    assert 'state: "on"' in block
    assert "entity_id: input_boolean.sleep_session_cpap_stopped" in block
    assert 'state: "off"' in block
    assert "entity_id: sensor.owner_suite_cpap_plug_power" in block
    assert "below: 1.3" in block
    assert "entity_id: input_datetime.sleep_session_cpap_off" in block
    assert "action: script.finalize_sleep_quality_session" in block


def test_reconcile_also_triggers_on_automation_reload() -> None:
    # Codex P2 follow-up on #373: a plain automation reload does not emit
    # homeassistant.start, so a debounce lost to a reload (not just a
    # restart) went unreconciled with only the start trigger.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    assert "event_type: automation_reloaded" in block


def test_reconcile_recovers_a_lost_bed_exit_debounce() -> None:
    # Codex P2 follow-up on #373: if cpap_stopped is already "on" (set
    # before the restart/reload, or just reconciled above) but the bed's
    # own separate bed_exit debounce was the one discarded, sleep_session_
    # bed_out is left holding a stale/prior value. The sole existing
    # reconcile branch required cpap_stopped == "off" and so never ran in
    # this case, leaving sleep_session_active latched on forever.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    bed_out_index = block.index("entity_id: input_datetime.sleep_session_bed_out")
    preceding = block[:bed_out_index]

    assert "entity_id: input_boolean.sleep_session_cpap_stopped" in preceding
    state_index = preceding.rindex("entity_id: input_boolean.sleep_session_cpap_stopped")
    guard_block = preceding[state_index:]
    assert 'state: "on"' in guard_block

    assert (
        "state_attr('input_datetime.sleep_session_bed_out', 'timestamp')"
        in block
    )


def test_reconcile_bed_exit_freshness_compares_against_current_transition() -> None:
    # Codex P2 follow-up on #373: comparing sleep_session_bed_out only
    # against sleep_session_bed_in (the session START) missed a later exit
    # within the SAME session whose debounce was lost after an earlier,
    # already-recorded exit-then-reentry — that earlier bed_out is still
    # newer than bed_in, so the prior-session-only staleness check let the
    # stale value stand. Comparing against the bed sensor's own last_changed
    # (the current, most recent off-transition) catches both cases.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    assert (
        "state_attr('input_datetime.sleep_session_bed_out', 'timestamp') | float(0))\n"
        "                 < as_timestamp(states.binary_sensor.bed_presence_2d0670_bed_occupied_either.last_changed)"
        in block
    )
    assert "state_attr('input_datetime.sleep_session_bed_in', 'timestamp')" not in block


def test_reconcile_requires_the_full_debounce_before_treating_a_transition_as_settled() -> None:
    # Codex P2 follow-up on #373: without their own `for:` guard, a reload
    # moments after a genuine CPAP-drop or bed-exit would let these
    # reconciliation branches treat the transition as already-settled
    # immediately, fast-tracking past the same 5-minute debounce a normal
    # trigger would still be waiting out — turning a brief power dip or
    # temporary bed exit into a premature end-of-session.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    cpap_stop_index = block.index("below: 1.3")
    cpap_stop_guard = block[cpap_stop_index : cpap_stop_index + 60]
    assert "minutes: 5" in cpap_stop_guard

    bed_exit_index = block.index(
        "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either\n            state: \"off\""
    )
    bed_exit_guard = block[bed_exit_index : bed_exit_index + 140]
    assert "minutes: 5" in bed_exit_guard


def test_reconcile_recovers_a_lost_cpap_start_debounce() -> None:
    # Codex P2 follow-up on #373: sleep_quality_prepare_session's cpap_start
    # trigger has its own 10-second `for:` debounce. If that debounce is
    # discarded by a restart/reload mid-flight and the sensor never crosses
    # the threshold again, no session is ever started for that CPAP run —
    # and the existing reconciliation branches all required
    # sleep_session_active to already be "on", so none of them could help.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    start_index = block.index('state: "off"')
    guard_block = block[start_index : start_index + 300]
    assert "entity_id: sensor.owner_suite_cpap_plug_power" in guard_block
    assert "above: 1.3" in guard_block
    assert "seconds: 10" in guard_block

    assert "entity_id: input_datetime.sleep_session_cpap_on" in block
    assert "action: counter.reset" in block
    assert "action: input_boolean.turn_on\n            target:\n              entity_id: input_boolean.sleep_session_active" in block


def test_owner_suite_dashboard_shows_recent_sleep_history() -> None:
    dashboard = DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "title: Sleep continuity (heuristic)" in dashboard
    assert "hours_to_show: 336" in dashboard
    assert "entity: input_number.sleep_quality_score" in dashboard
    assert "entity: counter.sleep_restlessness_events" in dashboard
    assert "entity: input_number.sleep_session_bed_minutes" in dashboard
    assert "entity: input_number.sleep_session_cpap_minutes" in dashboard
