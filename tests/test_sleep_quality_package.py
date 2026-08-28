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
    # The only template: use is the derived CPAP-debounce helper below, not
    # a substitute for persisted session state -- that must stay on native,
    # restorable input_datetime/input_number/counter helpers.
    assert text.count("\ntemplate:") == 1


def test_cpap_running_helper_is_debounced_and_guards_unavailable_readings() -> None:
    # Codex P2 follow-up on #373: the raw power sensor's own last_changed
    # resets on every in-range fluctuation, not just threshold crossings,
    # so it can't answer "has this been sustained above/below 1.3W for N
    # minutes" retrospectively -- and float(0) coercion would treat a
    # genuinely unavailable/unknown reading as a false "below threshold".
    # A debounced template helper (delay_on/delay_off, same pattern as
    # dryer_running in cleaning.yaml) fixes both: its own last_changed only
    # moves on a genuine, sustained crossing, and its availability template
    # keeps an unavailable sensor from reading as "off".
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    template_section = text.split("\ntemplate:", maxsplit=1)[1].split(
        "\nscript:", maxsplit=1
    )[0]

    assert "default_entity_id: binary_sensor.owner_suite_cpap_running" in template_section
    assert "has_value('sensor.owner_suite_cpap_plug_power')" in template_section
    assert (
        "state: \"{{ states('sensor.owner_suite_cpap_plug_power') | float(0) > 1.3 }}\""
        in template_section
    )
    assert "delay_on" in template_section
    assert "seconds: 10" in template_section
    assert "delay_off" in template_section
    assert "minutes: 5" in template_section


def test_bed_exit_without_session_clears_stale_pending_entry() -> None:
    # Codex P2 follow-up on #373: a qualifying nightly bed entry sets
    # bed_entry_pending on and records bed_in, but nothing ever cleared it
    # if the resident left the bed again without starting CPAP. A later,
    # unrelated CPAP start (e.g. daytime testing) would then inherit that
    # stale bed_in -- the finalizer's ordering check only requires
    # cpap_on_ts >= bed_in_ts (always true for an older bed_in), never
    # bed_out_ts >= cpap_on_ts, so the two unrelated periods would publish
    # as one bogus session. Clearing the pending flag when the bed empties
    # again without a session having started prevents that inheritance.
    prepare = _automation_block("sleep_quality_prepare_session")

    assert "id: bed_exit_without_session" in prepare
    branch = prepare.split("id: bed_exit_without_session", maxsplit=2)[2]
    turn_off_index = branch.index("action: input_boolean.turn_off")
    guard = branch[:turn_off_index]

    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in guard
    assert 'state: "on"' in guard

    target_index = branch.index(
        "entity_id: input_boolean.sleep_session_bed_entry_pending", turn_off_index
    )
    assert target_index > turn_off_index


def test_cpap_start_requires_pending_entry_or_nightly_window() -> None:
    # Codex P2 follow-up on #373: cpap_start had no time gate at all, unlike
    # bed_entry. Daytime CPAP testing with no pending nightly bed entry would
    # fall back to a synthetic bed_in (or inherit a stale one from the last
    # real session), forming a fully ordered but bogus session that
    # overwrites real overnight analytics once it finalizes. A pending
    # nightly bed entry must always be accepted regardless of the current
    # time (a late sleeper starting CPAP after the nightly window), but
    # absent that, cpap_start must require the same nightly window bed_entry
    # itself requires.
    prepare = _automation_block("sleep_quality_prepare_session")
    cpap_start_branch = prepare.split("id: cpap_start", maxsplit=2)[2]
    sequence_index = cpap_start_branch.index("sequence:")
    guard = cpap_start_branch[:sequence_index]

    assert "condition: or" in guard
    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in guard
    assert 'state: "on"' in guard
    assert "condition: time" in guard
    assert 'after: "18:00:00"' in guard
    assert 'before: "12:00:00"' in guard

    # Codex P2 follow-up on #373: bed occupancy must be required
    # unconditionally, not just for the nightly-window alternative -- a
    # reload that misses the live bed_exit_without_session trigger can leave
    # a pending entry stuck "on" after the bed has actually gone empty
    # again, so a stale pending entry alone must not be enough. The "or"
    # (pending entry / nightly window) must be nested inside an outer "and"
    # with the bed-occupancy check.
    assert "condition: and" in guard
    and_index = guard.index("condition: and")
    or_index = guard.index("condition: or", and_index)
    assert and_index < or_index

    occupancy_block = guard[and_index:or_index]
    assert "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either" in occupancy_block
    assert 'state: "on"' in occupancy_block

    or_block = guard[or_index:]
    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in or_block
    assert "condition: time" in or_block


def test_cpap_resume_banks_interruption_into_accumulated_active_time() -> None:
    # Codex P2 follow-up on #373: rearming the stop latch on a genuine
    # mid-session CPAP resumption left sleep_session_cpap_on unchanged, so a
    # later stop would overwrite cpap_off and finalize would compute the
    # duration from the ORIGINAL start straight through to that final stop --
    # counting the entire interruption as active CPAP use and inflating both
    # cpap_minutes and the continuity score. The ended interruption must be
    # banked into an accumulator and a fresh segment started at the resume,
    # only when genuinely re-arming (the latch was actually on).
    active = _automation_block("sleep_quality_track_active_session")
    cpap_resume_branch = active.split("id: cpap_resume", maxsplit=2)[2]

    guard_index = cpap_resume_branch.index(
        "entity_id: input_boolean.sleep_session_cpap_stopped"
    )
    guard = cpap_resume_branch[guard_index : guard_index + 90]
    assert 'state: "on"' in guard

    assert "entity_id: input_number.sleep_session_cpap_active_seconds" in cpap_resume_branch
    accumulate_index = cpap_resume_branch.index(
        "entity_id: input_number.sleep_session_cpap_active_seconds"
    )
    cpap_on_index = cpap_resume_branch.index(
        "entity_id: input_datetime.sleep_session_cpap_on", accumulate_index
    )
    turn_off_index = cpap_resume_branch.index(
        "action: input_boolean.turn_off", cpap_on_index
    )
    assert accumulate_index < cpap_on_index < turn_off_index

    accumulate_value = cpap_resume_branch[accumulate_index:cpap_on_index]
    assert "state_attr('input_datetime.sleep_session_cpap_off', 'timestamp')" in accumulate_value
    assert "state_attr('input_datetime.sleep_session_cpap_on', 'timestamp')" in accumulate_value


def test_cpap_start_resets_accumulated_active_time_for_a_fresh_session() -> None:
    prepare = _automation_block("sleep_quality_prepare_session")
    cpap_start_branch = prepare.split("id: cpap_start", maxsplit=2)[2]
    assert "entity_id: input_number.sleep_session_cpap_active_seconds" in cpap_start_branch
    accumulate_index = cpap_start_branch.index(
        "entity_id: input_number.sleep_session_cpap_active_seconds"
    )
    value_index = cpap_start_branch.index("value:", accumulate_index)
    assert cpap_start_branch[value_index : value_index + 10].strip() == "value: 0"


def test_finalize_adds_accumulated_active_time_to_cpap_minutes() -> None:
    finalize = _script_block("finalize_sleep_quality_session")
    cpap_minutes_index = finalize.index("cpap_minutes:")
    bed_transitions_index = finalize.index("bed_transitions:", cpap_minutes_index)
    cpap_minutes_template = finalize[cpap_minutes_index:bed_transitions_index]

    assert "cpap_off_ts - cpap_on_ts" in cpap_minutes_template
    assert (
        "states('input_number.sleep_session_cpap_active_seconds')"
        in cpap_minutes_template
    )


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
    # Only the cpap_stop trigger's own threshold remains a raw below: 1.3
    # — the bed_exit branch's finalize gate checks the debounced
    # binary_sensor.owner_suite_cpap_running helper instead, so a reading
    # sitting exactly at the boundary can't be classified differently by
    # the two gates (Codex P2 follow-up on #373).
    assert active.count("below: 1.3") == 1
    assert "entity_id: binary_sensor.owner_suite_cpap_running" in active


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


def test_cpap_start_timestamps_the_actual_transition_not_the_debounce_delay() -> None:
    # Codex P2 follow-up on #373: cpap_start's own 10-second `for:` debounce
    # made now() ten seconds late here too (same class of bug as the
    # already-fixed cpap_stop/bed_exit delay), under-reporting cpap_minutes.
    # The fallback bed_in write in the same branch must use the identical
    # source: if cpap_on switched to the earlier trigger timestamp while
    # bed_in stayed on now(), cpap_on_ts could read before bed_in_ts and
    # fail the finalizer's cpap_on_ts >= bed_in_ts check.
    prepare = _automation_block("sleep_quality_prepare_session")
    cpap_start_branch = prepare.split("id: cpap_start", maxsplit=2)[2]

    # Codex P2 follow-up on #373: a naive local datetime string is
    # ambiguous during the autumn DST fallback (a repeated wall-clock
    # hour). timestamp: (an absolute epoch) sidesteps that entirely.
    expected = 'timestamp: "{{ as_timestamp(trigger.to_state.last_changed) }}"'
    assert cpap_start_branch.count(expected) == 2
    assert "datetime: \"{{ now().strftime('%Y-%m-%d %H:%M:%S') }}\"" not in cpap_start_branch
    assert "strftime" not in cpap_start_branch


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

    # Codex P2 follow-up on #373: a naive local datetime string is
    # ambiguous during the autumn DST fallback (a repeated wall-clock
    # hour). timestamp: (an absolute epoch) sidesteps that entirely.
    expected = 'timestamp: "{{ as_timestamp(trigger.to_state.last_changed) }}"'
    assert expected in cpap_stop_branch
    assert expected in bed_exit_branch
    assert "datetime: \"{{ now().strftime('%Y-%m-%d %H:%M:%S') }}\"" not in cpap_stop_branch
    assert "datetime: \"{{ now().strftime('%Y-%m-%d %H:%M:%S') }}\"" not in bed_exit_branch
    assert "strftime" not in cpap_stop_branch
    assert "strftime" not in bed_exit_branch
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


def test_cpap_stop_requires_fresh_bed_out_before_finalizing() -> None:
    # Codex P2 follow-up on #373: matching bed_exit's 5-minute for: duration
    # is not enough on its own. If CPAP and the bed both go inactive at the
    # same time, both branches' debounces become eligible together, and this
    # branch's queued action can still run before bed_exit's has written the
    # current bed_out — even though the bed has technically been off for 5
    # minutes — because matching durations doesn't guarantee callback
    # execution order. Must also require sleep_session_bed_out to already be
    # at or past the bed sensor's own last_changed, same freshness check the
    # periodic reconciliation gate uses.
    active = _automation_block("sleep_quality_track_active_session")
    cpap_stop_branch = active.split("id: cpap_stop", maxsplit=2)[2]
    finalize_index = cpap_stop_branch.index("action: script.finalize_sleep_quality_session")
    preceding = cpap_stop_branch[:finalize_index]

    assert (
        "(state_attr('input_datetime.sleep_session_bed_out', 'timestamp') | float(0)) | int"
        in preceding
    )
    assert (
        ">= (as_timestamp(states.binary_sensor.bed_presence_2d0670_bed_occupied_either.last_changed) | int)"
        in preceding
    )


def test_cpap_stop_ignores_repeat_firings_while_already_latched_stopped() -> None:
    # Codex P2 follow-up on #373: a power spike above 1.3W lasting under 10
    # seconds is too brief to fire cpap_resume or clear
    # sleep_session_cpap_stopped, but it does reset the cpap_stop trigger's
    # own raw numeric_state for: timer. Without a guard, a second
    # below-1.3-for-5-minutes firing while the original stop is still
    # latched on would overwrite cpap_off with this later, spurious repeat,
    # extending the reported CPAP duration through the entire interval CPAP
    # was actually already stopped. The write must only happen while
    # sleep_session_cpap_stopped is still off.
    active = _automation_block("sleep_quality_track_active_session")
    cpap_stop_branch = active.split("id: cpap_stop", maxsplit=2)[2]
    cpap_off_index = cpap_stop_branch.index(
        "entity_id: input_datetime.sleep_session_cpap_off"
    )
    turn_on_index = cpap_stop_branch.index(
        "action: input_boolean.turn_on", cpap_off_index
    )
    guard_end = cpap_stop_branch.index(
        "entity_id: input_boolean.sleep_session_cpap_stopped", turn_on_index
    )
    preceding_guard = cpap_stop_branch[:guard_end]

    state_index = preceding_guard.rindex(
        "entity_id: input_boolean.sleep_session_cpap_stopped"
    )
    guard_block = preceding_guard[state_index:cpap_off_index]
    assert 'state: "off"' in guard_block


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
    assert "entity_id: binary_sensor.owner_suite_cpap_running" in block
    assert "entity_id: input_datetime.sleep_session_cpap_off" in block
    assert "action: script.finalize_sleep_quality_session" in block


def test_reconcile_also_triggers_on_automation_reload() -> None:
    # Codex P2 follow-up on #373: a plain automation reload does not emit
    # homeassistant.start, so a debounce lost to a reload (not just a
    # restart) went unreconciled with only the start trigger.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    assert "event_type: automation_reloaded" in block


def test_reconcile_rechecks_periodically_after_a_restart_resets_last_changed() -> None:
    # Codex P2 follow-up on #373: HA resets a restored entity's last_changed
    # to the restore moment, so a per-branch `for:` debounce guard almost
    # never reads as satisfied on the single, one-shot homeassistant.start
    # evaluation — and with no delayed or state-triggered follow-up, the
    # reconciliation was simply missed. A periodic re-check lets the same
    # guard naturally pass once real time has elapsed since the restore.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    assert "trigger: time_pattern" in block
    assert 'minutes: "/5"' in block


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

    # cpap_start reconcile, re-arm, cpap_stop reconcile, and the trailing
    # finalize gate all check this same debounced helper.
    assert block.count("entity_id: binary_sensor.owner_suite_cpap_running") == 4
    cpap_stop_branch = block.split("Reconcile a lost cpap_stop debounce", maxsplit=1)[1]
    cpap_stop_index = cpap_stop_branch.index("entity_id: binary_sensor.owner_suite_cpap_running")
    cpap_stop_guard = cpap_stop_branch[cpap_stop_index : cpap_stop_index + 90]
    assert 'state: "off"' in cpap_stop_guard

    bed_exit_branch = block.split("Reconcile a lost bed_exit debounce", maxsplit=1)[1]
    bed_exit_index = bed_exit_branch.index(
        "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either\n            state: \"off\""
    )
    bed_exit_guard = bed_exit_branch[bed_exit_index : bed_exit_index + 140]
    assert "minutes: 5" in bed_exit_guard


def test_reconcile_condition_never_puts_for_on_a_numeric_state_condition() -> None:
    # Codex P1 follow-up on #373: `for:` is only supported on numeric_state
    # TRIGGERS and on state CONDITIONS, not on numeric_state CONDITIONS —
    # Home Assistant's schema rejects that combination as an unsupported
    # extra key, which would fail to load. This automation must therefore
    # never put `for:` on a numeric_state condition.
    #
    # Codex P2 follow-up on #373: a template comparing the raw power
    # sensor's own last_changed against now() was tried as a replacement,
    # but that resets on every in-range wattage fluctuation too, so it
    # never reached the guard duration while a session was genuinely
    # ongoing. All three duration checks instead read the debounced
    # binary_sensor.owner_suite_cpap_running helper (delay_on/delay_off do
    # the debouncing), whose own last_changed only moves on a genuine,
    # sustained crossing.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    for match in re.finditer(r"condition: numeric_state\n(?:.+\n)*?", block):
        segment = block[match.start() : match.start() + 120]
        assert "for:" not in segment

    assert block.count("condition: state\n            entity_id: binary_sensor.owner_suite_cpap_running") == 4


def test_reconcile_clears_pending_bed_entry_missed_by_restart() -> None:
    # Codex P2 follow-up on #373: sleep_quality_prepare_session's live
    # bed_exit_without_session trigger only clears a stale
    # sleep_session_bed_entry_pending if it's actually running when the
    # bed empties. If HA restarts or automations reload while the bed is
    # already empty (or becomes empty during the gap), that transition is
    # never delivered, leaving the pending flag stuck on so a later,
    # unrelated CPAP start could still inherit the stale bed_in. This
    # reconciliation branch must run before the cpap_start reconcile
    # branch, so a stale flag can't also suppress that branch's fallback.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    reconcile_index = block.index("Reconcile a pending bed-entry")
    recover_entry_index = block.index("Recover a nightly bed entry")
    cpap_start_index = block.index("Reconcile a lost cpap_start debounce")
    assert reconcile_index < recover_entry_index < cpap_start_index

    branch = block[reconcile_index:recover_entry_index]
    assert "entity_id: input_boolean.sleep_session_active" in branch
    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in branch
    assert "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either" in branch
    assert branch.count('state: "off"') == 2
    assert 'state: "on"' in branch
    assert "action: input_boolean.turn_off" in branch


def test_reconcile_recovers_a_bed_entry_missed_during_downtime() -> None:
    # Codex P2 follow-up on #373: if HA is down when the resident gets
    # into bed and returns before CPAP starts, the live bed_entry
    # off->on trigger is never delivered, so sleep_session_bed_entry_
    # pending stays off. A later CPAP start's fallback would then use its
    # own (later) transition as bed_in, silently omitting the observed
    # in-bed interval from bed_minutes. Must run before the cpap_start
    # reconcile branch so that branch's own fallback doesn't overwrite
    # this earlier, approximate bed_in with the later CPAP time, and must
    # respect the same nightly time window the live bed_entry trigger
    # uses so a daytime bed visit isn't recorded as a session start.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    recover_entry_index = block.index("Recover a nightly bed entry")
    cpap_start_index = block.index("Reconcile a lost cpap_start debounce")
    assert recover_entry_index < cpap_start_index

    branch = block[recover_entry_index:cpap_start_index]
    assert "entity_id: input_boolean.sleep_session_active" in branch
    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in branch
    assert "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either" in branch
    assert branch.count('state: "off"') == 2
    assert 'state: "on"' in branch
    assert 'after: "18:00:00"' in branch
    assert 'before: "12:00:00"' in branch
    assert "entity_id: input_datetime.sleep_session_bed_in" in branch
    assert "action: input_boolean.turn_on" in branch


def test_reconcile_recovers_a_lost_cpap_start_debounce() -> None:
    # Codex P2 follow-up on #373: sleep_quality_prepare_session's cpap_start
    # trigger has its own 10-second `for:` debounce. If that debounce is
    # discarded by a restart/reload mid-flight and the sensor never crosses
    # the threshold again, no session is ever started for that CPAP run —
    # and the existing reconciliation branches all required
    # sleep_session_active to already be "on", so none of them could help.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    cpap_start_branch = block.split("Reconcile a lost cpap_start debounce", maxsplit=1)[1]

    start_index = cpap_start_branch.index('state: "off"')
    then_index = cpap_start_branch.index("then:", start_index)
    guard_block = cpap_start_branch[start_index:then_index]
    assert "entity_id: sensor.owner_suite_cpap_plug_power" not in guard_block
    assert "entity_id: binary_sensor.owner_suite_cpap_running" in guard_block
    assert 'state: "on"' in guard_block

    assert "entity_id: input_datetime.sleep_session_cpap_on" in block
    assert "action: counter.reset" in block
    assert "action: input_boolean.turn_on\n            target:\n              entity_id: input_boolean.sleep_session_active" in block


def test_reconcile_cpap_start_requires_pending_entry_or_nightly_window() -> None:
    # Codex P2 follow-up on #373: same nightly-context gap as the live
    # cpap_start branch, but here on the periodic reconciliation path. CPAP
    # running during daytime testing with no pending nightly bed entry could
    # let this periodic tick recover a synthetic session the same way the
    # live trigger could, overwriting real overnight analytics once it
    # finalizes. A pending nightly bed entry must always be accepted
    # regardless of the current time; absent that, this recovery must
    # require the same nightly window the live cpap_start branch requires.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    cpap_start_branch = block.split("Reconcile a lost cpap_start debounce", maxsplit=1)[1]

    then_index = cpap_start_branch.index("then:")
    guard_block = cpap_start_branch[:then_index]

    assert "condition: or" in guard_block
    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in guard_block
    assert 'state: "on"' in guard_block
    assert "condition: time" in guard_block
    assert 'after: "18:00:00"' in guard_block
    assert 'before: "12:00:00"' in guard_block

    # Codex P2 follow-up on #373: bed occupancy must be required
    # unconditionally here too, not just for the nightly-window alternative
    # -- a reload that misses the live bed_exit_without_session trigger can
    # leave a pending entry stuck "on" after the bed has actually gone empty
    # again. The "or" (pending entry / nightly window) must be nested inside
    # an outer "and" with the bed-occupancy check.
    assert "condition: and" in guard_block
    and_index = guard_block.index("condition: and")
    or_index = guard_block.index("condition: or", and_index)
    assert and_index < or_index

    occupancy_block = guard_block[and_index:or_index]
    assert "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either" in occupancy_block
    assert 'state: "on"' in occupancy_block

    or_block = guard_block[or_index:]
    assert "entity_id: input_boolean.sleep_session_bed_entry_pending" in or_block
    assert "condition: time" in or_block


def test_active_session_rearms_cpap_stopped_latch_in_real_time_on_resume() -> None:
    # Codex P2 follow-up on #373: relying only on the periodic reconciliation
    # tick to clear a stale sleep_session_cpap_stopped latch left it stuck
    # on between ticks. If CPAP resumed and then dropped again entirely
    # within that window, the bed_exit branch below (which only checks
    # cpap_stopped == on plus CPAP's raw current state) could finalize
    # using the old cpap_off before the new drop's own 5-minute debounce
    # completed. A real-time trigger clears the latch the moment CPAP
    # genuinely resumes, independent of the periodic tick.
    active = _automation_block("sleep_quality_track_active_session")

    assert "id: cpap_resume" in active
    trigger_index = active.index("id: cpap_resume")
    trigger_def = active[max(0, trigger_index - 120) : trigger_index]
    assert "above: 1.3" in trigger_def
    assert "seconds: 10" in trigger_def

    resume_branch = active.split("id: cpap_resume", maxsplit=2)[2]
    turn_off_index = resume_branch.index("action: input_boolean.turn_off")
    target_index = resume_branch.index(
        "entity_id: input_boolean.sleep_session_cpap_stopped", turn_off_index
    )
    assert target_index > turn_off_index


def test_finalize_gates_use_a_single_consistent_cpap_threshold_source() -> None:
    # Codex P2 follow-up on #373: numeric_state "above" and "below" are
    # both strict, so a power reading sitting exactly at 1.3W is
    # classified as neither -- but the debounced helper is a plain
    # boolean and must commit to one side. If some finalize gates checked
    # the raw sensor with below: 1.3 while others (or the branch that
    # latches sleep_session_cpap_stopped) checked the helper, a reading
    # pinned at exactly 1.3W could make the reconciliation branch believe
    # CPAP had stopped while a finalize gate never agreed, latching
    # sleep_session_active forever. Every finalize-relevant gate must
    # check the same helper, not a raw numeric threshold.
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    # The only remaining raw below: 1.3 is the cpap_stop trigger itself
    # (which sets the helper's own debounced state, not a competing
    # classification of it).
    assert text.count("below: 1.3") == 1
    assert "condition: numeric_state\n            entity_id: sensor.owner_suite_cpap_plug_power\n            below: 1.3" not in text


def test_reconcile_final_gate_requires_bed_debounce_and_current_bed_out() -> None:
    # Codex P2 follow-up on #373: the trailing periodic finalize check used
    # the bed's raw instantaneous "off" state. If the CPAP-stop branch just
    # above flips cpap_stopped on while the bed has been empty less than 5
    # minutes, this check could finalize immediately — before the bed_exit
    # reconcile branch (or the normal automation) had written the current
    # bed_out — discarding the session against a stale timestamp. It must
    # require the same 5-minute debounce as bed_exit, plus a bed_out that is
    # already current for this exit.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    final_gate = block.rsplit("if:", maxsplit=1)[1]

    assert "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either" in final_gate
    assert 'state: "off"' in final_gate
    assert "minutes: 5" in final_gate
    assert (
        "state_attr('input_datetime.sleep_session_bed_out', 'timestamp') | float(0)) | int\n"
        "                 >= (as_timestamp(states.binary_sensor.bed_presence_2d0670_bed_occupied_either.last_changed) | int)"
        in final_gate
    )


def test_reconcile_final_gate_requires_cpap_currently_below_threshold() -> None:
    # Codex P2 follow-up on #373: sleep_session_cpap_stopped latches on and
    # is never reset if CPAP resumes mid-session after a genuine 5-minute
    # interruption. Without also checking CPAP's current reading, the
    # periodic reconciliation could finalize using a stale earlier cpap_off
    # while CPAP is actively running again. Require CPAP to currently read
    # below threshold too, matching the normal bed_exit branch's own guard.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    final_gate = block.rsplit("if:", maxsplit=1)[1]

    # Checks the debounced helper rather than a raw below: 1.3 numeric
    # condition, so a reading sitting exactly at the threshold can't be
    # classified differently here than by the cpap_stop reconcile branch
    # that sets sleep_session_cpap_stopped in the first place (Codex P2
    # follow-up on #373).
    assert "entity_id: binary_sensor.owner_suite_cpap_running" in final_gate
    assert 'state: "off"' in final_gate


def test_reconcile_writes_preserve_the_actual_transition_time() -> None:
    # Codex P2 follow-up on #373: these recovery writes used now() — the
    # periodic-tick or restart/reload evaluation time — rather than the
    # real transition, inflating (or shrinking) the recovered cpap_on,
    # cpap_off, and bed_out by however long the debounce plus the wait for
    # the next reconciliation tick took. Each entity's own last_changed is
    # the real transition (exact across a reload, and at least the restore
    # time after a restart), which the guarding `for:` condition already
    # confirms has held continuously.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    # cpap_on and the fallback bed_in back the CPAP debounce helper's own
    # delay_on out of its last_changed to recover the real crossing time;
    # cpap_off backs its delay_off out the same way; the mid-session re-arm
    # branch's own fresh-segment cpap_on write backs delay_on out again
    # (Codex P2 follow-up on #373: excluding stopped intervals from CPAP
    # minutes). timestamp:/as_timestamp() (an absolute epoch) rather than
    # datetime:/strftime() (a naive local string) also sidesteps the autumn
    # DST fallback (Codex P2 follow-up on #373).
    assert block.count("as_timestamp(states.binary_sensor.owner_suite_cpap_running.last_changed") == 4
    assert block.count("- timedelta(seconds=10))") == 3
    assert block.count("- timedelta(minutes=5))") == 1
    assert (
        "as_timestamp(states.binary_sensor.bed_presence_2d0670_bed_occupied_either.last_changed)"
        in block
    )
    assert 'datetime: "{{ now().strftime(\'%Y-%m-%d %H:%M:%S\') }}"' not in block
    assert "strftime" not in block


def test_reconcile_cpap_start_fallback_bed_in_matches_cpap_on_ordering() -> None:
    # Codex P2 follow-up on #373: the finalizer requires cpap_on_ts >=
    # bed_in_ts. The fallback bed_in write (used when no separate bed-entry
    # is pending) stamped now() -- the reconciliation tick's time -- while
    # cpap_on right below it stamped the CPAP sensor's own, earlier
    # last_changed. A recovered session's bed_in could then read later than
    # its own cpap_on, always failing that ordering check and discarding
    # the session's analytics. Both must derive from the same CPAP
    # transition.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")
    cpap_start_branch = block.split("state: \"off\"", maxsplit=1)[1]

    bed_in_index = cpap_start_branch.index("input_datetime.sleep_session_bed_in")
    cpap_on_index = cpap_start_branch.index("input_datetime.sleep_session_cpap_on")
    assert bed_in_index < cpap_on_index

    between = cpap_start_branch[bed_in_index:cpap_on_index]
    assert "as_timestamp(states.binary_sensor.owner_suite_cpap_running.last_changed" in between
    assert "- timedelta(seconds=10))" in between


def test_reconcile_rearms_cpap_stopped_latch_when_cpap_resumes() -> None:
    # Codex P2 follow-up on #373: sleep_session_cpap_stopped latches on
    # during a mid-session CPAP interruption and nothing ever clears it once
    # CPAP resumes, so a later periodic tick could finalize using that
    # stale interruption's cpap_off the moment the bed happened to be
    # empty, rather than requiring a fresh stop. Re-arm the latch once CPAP
    # has genuinely resumed for its own 10-second debounce.
    block = _automation_block("sleep_quality_reconcile_cpap_stop_after_restart")

    rearm_branch = block.split("Re-arm the CPAP-stop latch", maxsplit=1)[1]
    turn_off_index = rearm_branch.index("action: input_boolean.turn_off")
    guard = rearm_branch[:turn_off_index]

    assert guard.count('state: "on"') == 3
    assert "entity_id: binary_sensor.owner_suite_cpap_running" in guard

    # The re-arm must run before the final finalize gate so a resumed
    # session's stale latch is cleared in the same evaluation pass.
    final_gate_index = block.rindex("if:")
    assert turn_off_index < final_gate_index

    # Codex P2 follow-up on #373: same as the real-time cpap_resume re-arm
    # -- this periodic re-arm must also bank the ended interruption into
    # the accumulator and start a fresh segment, or a resume recovered only
    # here (e.g. after a restart/reload swallowed the real-time trigger)
    # would still count the whole stopped interval as active CPAP use.
    assert "entity_id: input_number.sleep_session_cpap_active_seconds" in guard
    accumulate_index = guard.index("entity_id: input_number.sleep_session_cpap_active_seconds")
    cpap_on_index = guard.index(
        "entity_id: input_datetime.sleep_session_cpap_on", accumulate_index
    )
    assert accumulate_index < cpap_on_index < turn_off_index
    accumulate_value = guard[accumulate_index:cpap_on_index]
    assert "state_attr('input_datetime.sleep_session_cpap_off', 'timestamp')" in accumulate_value
    assert "state_attr('input_datetime.sleep_session_cpap_on', 'timestamp')" in accumulate_value


def test_owner_suite_dashboard_shows_recent_sleep_history() -> None:
    dashboard = DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "title: Sleep continuity (heuristic)" in dashboard
    assert "hours_to_show: 336" in dashboard
    assert "entity: input_number.sleep_quality_score" in dashboard
    assert "entity: counter.sleep_restlessness_events" in dashboard
    assert "entity: input_number.sleep_session_bed_minutes" in dashboard
    assert "entity: input_number.sleep_session_cpap_minutes" in dashboard
