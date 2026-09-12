from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"
CLEANING_PATH = ROOT / "packages" / "cleaning.yaml"


def _script_block(path: Path, script_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    target = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == target:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script block {script_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            end = index
            break

    return "\n".join(lines[start:end])


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


# Design note (post-Codex-review revision): the phase-tracking signal is the
# orchestrator script's OWN entity state (script.x40_ultra_main_level_mop_after_vacuum,
# 'on' for the full duration of both stages), not a separately-tracked
# input_boolean. Two rounds of Codex review found real gaps in the
# hand-maintained-latch approach (a false "Cleaning complete" on the interim
# dock; a stale "on" surviving script.reload since it cancels the parent
# script without recreating input_booleans; a reset-ordering race in
# x40_ultra_segment_vacuum_only). Reading the script entity's live state
# instead eliminates the whole class of staleness bugs: it needs no
# `initial:`, no reset-on-every-call plumbing, and no segment-script special
# case, because a script entity's on/off state is inherently correct across
# ANY interruption (HA restart, script.reload, a manual stop) with nothing to
# keep in sync.


def test_vacuum_only_has_no_phase_tracking_of_its_own() -> None:
    # The phase signal now lives entirely in the orchestrator
    # (x40_ultra_main_level_mop_after_vacuum)'s own entity state, so the
    # child vacuum-only script needs no two_stage field or flag plumbing.
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_vacuum_only")

    assert "two_stage" not in block
    assert "x40_ultra_mop_after_current_pass" not in block


def test_segment_vacuum_only_has_no_phase_tracking_of_its_own() -> None:
    # A segment clean is a different script entity entirely, so it is
    # automatically unaffected by the orchestrator's state — no explicit
    # reset needed (unlike the old input_boolean design, which required one).
    block = _script_block(VACUUM_PATH, "x40_ultra_segment_vacuum_only")

    assert "x40_ultra_mop_after_current_pass" not in block


def test_mop_after_vacuum_has_no_leftover_flag_plumbing() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    assert "x40_ultra_mop_after_current_pass" not in block
    # No `data: {two_stage: true}` needed on the vacuum-only call either.
    vacuum_call_index = block.index("action: script.x40_ultra_main_level_vacuum_only")
    next_line = block[vacuum_call_index : vacuum_call_index + 120].splitlines()[1]
    assert "data:" not in next_line


def test_input_boolean_helper_removed() -> None:
    text = VACUUM_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_mop_after_current_pass:" not in text


def test_live_activity_runs_in_parallel_mode() -> None:
    # Round 6, Codex P2: mode: queued forces a triggered instance's condition
    # evaluation to wait behind every earlier queued instance (including a
    # 2-minute delay branch), which can happen well after the trigger fired
    # — long enough for OTHER entities' state (the orchestrator script, in
    # this case) to have already moved on by the time it's finally checked.
    # This is the second time that exact bug shape has recurred against two
    # different guards (a mode-select check, then a script-state check), so
    # the actual fix is structural: mode: parallel starts a triggered
    # instance essentially immediately, closing the window to ordinary async
    # scheduling latency instead of an unbounded queue wait.
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    mode_index = block.index("\n    mode:")
    assert block[mode_index : mode_index + 20] == "\n    mode: parallel\n"


def test_live_activity_triggers_on_mode_and_orchestrator_state() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert "entity_id: select.x40_ultra_cleaning_mode" in block
    assert "entity_id: script.x40_ultra_main_level_mop_after_vacuum" in block
    assert "input_boolean.x40_ultra_mop_after_current_pass" not in block


def test_live_activity_completion_branch_suppressed_while_orchestrator_runs() -> None:
    # Round 3 of Codex review: a mode-based ("still sweeping") guard read LIVE
    # state at whatever moment a queued instance happened to dequeue. The fix
    # dropped the mode check entirely: suppress for the WHOLE window the
    # orchestrator script is "on" (interim AND final dock alike), since the
    # orchestrator now resolves the notification itself on all of its own
    # outcomes — nothing here needs to guess which dock this is.
    #
    # Round 6 found the SAME class of bug recurring even against this
    # script-state check: under mode: queued, a dock trigger could still
    # dequeue AFTER the orchestrator had already posted its own outcome and
    # gone "off", so the generic branch would fire anyway and overwrite an
    # accurate "Mop pass did not finish cleanly"/"mop skipped" message with a
    # generic "Cleaning complete". See test_live_activity_runs_in_parallel_mode
    # for the actual fix (mode: parallel, not another condition patch).
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # Anchor on the template's literal end, not the bare phrase: several
    # earlier code comments on this branch also mention "Cleaning complete"
    # in prose, which would otherwise match first.
    complete_index = block.index("%}Cleaning complete{% endif %}")
    preceding = block[:complete_index]

    guard_index = preceding.rindex("entity_id: script.x40_ultra_main_level_mop_after_vacuum")
    guard = preceding[guard_index : guard_index + 120]

    assert 'state: "off"' in guard
    # No mode-based condition should remain on this branch at all.
    assert "select.x40_ultra_cleaning_mode" not in preceding[preceding.rindex("- conditions:") :]


def test_mop_only_has_its_own_run_scoped_completion_latch() -> None:
    # Codex P2: x40_ultra_main_level_mop_only can fail to complete (rejected
    # mode, no-op start, or a real run that never reached `completed`)
    # WITHOUT erroring — it just returns normally. x40_ultra_mop_pass_pending
    # cannot signal that failure on its own: it is a cross-run "mop owed"
    # debt flag that can already read "off" on entry (time-based due, not a
    # forced retry), so a failure that started already-off would look
    # identical to a success. A dedicated run-scoped latch (reset off at
    # start, set on only on a real `completed` finish — the same pattern as
    # x40_ultra_vacuum_pass_completed) is needed to tell them apart.
    text = VACUUM_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_mop_pass_completed:" in text

    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_only")
    reset_index = block.index("action: input_boolean.turn_off")
    assert "x40_ultra_mop_pass_completed" in block[reset_index : reset_index + 150]

    set_on_index = block.rindex("action: input_boolean.turn_on")
    assert "x40_ultra_mop_pass_completed" in block[set_on_index : set_on_index + 150]
    # The set-on-success step must sit alongside setting last_mopped_at /
    # clearing the pending debt, i.e. inside the genuine `completed` branch.
    assert "input_datetime.x40_ultra_last_mopped_at" in block[: set_on_index][-400:]

    # Round 5, Codex P2: the reset must come BEFORE the bare pet-policy
    # condition, which STOPS the script outright when it fails (e.g. the
    # policy changed away from Unattended during the preceding vacuum pass).
    # A reset placed after that gate would be skipped entirely whenever the
    # gate halts the script, leaving a stale "on" from a PREVIOUS successful
    # mop in place — which x40_ultra_main_level_mop_after_vacuum's completion
    # check would then misread as this run having succeeded.
    policy_condition_index = block.index("Mopping requires explicit unattended pet policy")
    assert reset_index < policy_condition_index


def test_mop_after_vacuum_checks_mop_completion_latch_not_pending_flag() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    mop_only_index = block.index("action: script.x40_ultra_main_level_mop_only")
    then_index = block.index("then:")
    # The OUTER else (vacuum-skip branch) starts with its distinctive
    # notify.all action; a bare "else:" would instead match the NEW inner
    # if/else this fix adds (Cleaning complete vs. Mop pass did not finish
    # cleanly), which sits between here and the outer else.
    outer_else_marker = block.index("action: notify.all")
    assert then_index < mop_only_index < outer_else_marker

    success_section = block[mop_only_index:outer_else_marker]
    assert "x40_ultra_mop_pass_completed" in success_section
    assert "message: Cleaning complete" in success_section
    assert "Mop pass did not finish cleanly" in success_section

    # The 2-minute wait-then-clear moved OUT of this script entirely (Codex
    # P2: a delay inside this script is cancelled outright by script.reload,
    # stranding the notification with nothing left to run the clear); it now
    # lives in packages/cleaning.yaml, keyed off this script's own end.
    assert "delay:" not in success_section
    assert "clear_notification" not in success_section


def test_mop_after_vacuum_skip_branch_has_no_in_script_delay() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    # A bare "else:" would match the NEW inner if/else added to the success
    # branch first; the outer else (this skip branch) starts with its
    # distinctive notify.all action instead.
    outer_else_marker = block.index("action: notify.all")
    skip_section = block[outer_else_marker:]

    assert "mop was" in skip_section  # the existing notify.all skip message
    assert "tag: x40_vacuum" in skip_section
    assert "live_update: true" in skip_section
    # Same reasoning as the success branch: no delay/clear left in the script.
    assert "delay:" not in skip_section
    assert "clear_notification" not in skip_section


def test_live_activity_finalizes_orchestrator_end_outside_the_script() -> None:
    # The wait-then-clear for ALL of the orchestrator's outcomes now lives
    # here, keyed off its on->off transition, specifically because an
    # automation (unlike a script) is immune to script.reload.
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert 'entity_id: script.x40_ultra_main_level_mop_after_vacuum\n        to: "off"' in block
    assert "id: orchestrator_end" in block

    # "id: orchestrator_end" appears three times: the trigger definition,
    # this finalize branch (requires docked), and the "died mid-run" branch
    # added in round 7 (requires still cleaning/returning/paused) — anchor
    # on the exact condition-block text unique to THIS branch.
    branch_index = block.index(
        "id: orchestrator_end\n              - condition: state\n"
        "                entity_id: vacuum.x40_ultra\n                state: docked"
    )
    finalize_section = block[branch_index : branch_index + 1800]
    assert "state: docked" in finalize_section
    assert "delay:" in finalize_section
    assert "clear_notification" in finalize_section


def test_live_activity_mopping_label_gated_on_orchestrator_state() -> None:
    # A standalone/manual mop (started directly, or from the Dreame app) is
    # not part of an orchestrated two-stage run, so it must not be labeled
    # "(2/2)" — only a genuine two-stage run (orchestrator script running)
    # earns the phase count; otherwise it's plain "Mopping".
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert "is_state('script.x40_ultra_main_level_mop_after_vacuum', 'on')" in block
    assert "'mopping' and two_stage %}Mopping{{ rs }} (2/2)" in block
    assert "elif mode == 'mopping'\n" in block


def test_live_activity_message_is_phase_aware() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # Distinguishes the two stages by name.
    assert "Mopping" in block
    assert "Vacuuming" in block

    # A phase count is only shown while the orchestrator is actually running;
    # a single-stage run (vacuum or mop) gets no phase count at all.
    assert "(1/2)" in block
    assert "(2/2)" in block
    assert "two_stage" in block

    # Mop-phase visuals are distinct from the vacuum-phase blue used elsewhere
    # in this same automation (error/complete/vacuum branches).
    assert "mdi:water" in block
    assert "#00ACC1" in block


def test_notification_token_declared_and_bumped_every_run() -> None:
    text = CLEANING_PATH.read_text(encoding="utf-8")
    assert "x40_vacuum_notification_token:" in text

    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")
    # Bumped as the very first action, before `choose:` — i.e. on every run
    # of this automation, regardless of which (if any) branch matches.
    action_index = block.index("\n    action:")
    choose_index = block.index("- choose:")
    preamble = block[action_index:choose_index]
    assert "input_text.set_value" in preamble
    assert "x40_vacuum_notification_token" in preamble


def test_delayed_clears_check_notification_token_not_vacuum_state() -> None:
    # Round 8, Codex P2: checking "vacuum isn't cleaning/returning/paused"
    # wasn't enough — a queued follow-up run (x40_ultra_main_level_policy_clean
    # is itself mode: queued; observed in practice starting 13 seconds after
    # a trip's full-floor pass docked) could already be showing an error, or
    # have already finished a short segment and posted its OWN terminal
    # message, by the time an older 2-minute delay wakes up — neither of
    # which is "vacuum is active", yet clearing in either case would erase a
    # newer, unrelated update. Generalized to a shared token bumped by every
    # run of this automation: a delayed clear captures it right before
    # sleeping and only fires if nothing has touched it since.
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    capture_positions = [
        i for i in range(len(block)) if block.startswith("our_token:", i)
    ]
    assert len(capture_positions) == 2, "expected exactly two captures (orchestrator_end + generic completion)"

    for pos in capture_positions:
        following = block[pos : pos + 1300]
        assert 'delay: "00:02:00"' in following
        assert "states('input_text.x40_vacuum_notification_token') == our_token" in following
        assert "clear_notification" in following
        # The old vacuum-state-based check must be gone from this guard.
        assert "condition: not" not in following


def test_orchestrator_interrupted_marker_declared() -> None:
    text = CLEANING_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_orchestrator_interrupted:" in text
    # No `initial:` — unlike the removed phase flag, the fact that a prior
    # run was left interrupted stays true across a later HA restart.
    marker_index = text.index("x40_ultra_orchestrator_interrupted:")
    declaration = text[marker_index : marker_index + 200]
    assert "initial:" not in declaration


def test_live_activity_records_orchestrator_death_before_docking() -> None:
    # Round 7, Codex P2: if script.reload (packages/media_player.yaml)
    # cancels the orchestrator mid-vacuum-stage, the robot keeps cleaning
    # autonomously and docks on its own later. The orchestrator_end trigger
    # fires immediately (script.reload recreates the script entity as
    # "off"), but at THAT moment the vacuum is still active, not docked.
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # x40_ultra_orchestrator_interrupted is set in TWO places now: this
    # branch (script.reload mid-run) and a round-8 boot-reconciliation branch
    # (HA restart mid-run) — anchor specifically on the one keyed off the
    # orchestrator_end trigger with the robot still active.
    anchor = (
        "id: orchestrator_end\n              - condition: state\n"
        "                entity_id: vacuum.x40_ultra\n                state:\n"
        "                  - cleaning\n                  - returning\n"
        "                  - paused"
    )
    branch_index = block.index(anchor)
    branch = block[branch_index : branch_index + 400]

    assert "x40_ultra_orchestrator_interrupted" in branch
    assert "action: input_boolean.turn_on" in branch
    assert "action: input_boolean.turn_on" in branch


def test_generic_completion_branch_reports_interrupted_outcome() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    complete_index = block.index("%}Cleaning complete{% endif %}")
    # This is a template branch, not the literal skip/incomplete messages
    # used elsewhere, so anchor on the surrounding message template instead
    # of a literal string.
    message_start = block.rindex("message: >-", 0, complete_index)
    message_template = block[message_start : complete_index + 60]

    assert "x40_ultra_orchestrator_interrupted" in message_template
    assert "interrupted before completing" in message_template

    # The marker must be cleared once consumed, so a later genuine
    # single-stage completion isn't also mislabeled as interrupted.
    turn_off_index = block.index("action: input_boolean.turn_off", complete_index)
    turn_off_section = block[turn_off_index : turn_off_index + 150]
    assert "x40_ultra_orchestrator_interrupted" in turn_off_section


def test_orchestrated_run_active_survives_restart_for_boot_reconciliation() -> None:
    # Round 8, Codex P2: a full HA restart (not just script.reload) during
    # the vacuum stage leaves NO trace for orchestrator_end to observe — the
    # automation is gone too, so it never fires, and the script simply
    # reappears "off" with no memory of having been "on". This marker exists
    # only to survive that (no `initial:`), set by the orchestrator itself.
    text = VACUUM_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_orchestrated_run_active:" in text
    marker_index = text.index("x40_ultra_orchestrated_run_active:")
    declaration = text[marker_index : marker_index + 300]
    assert "initial:" not in declaration

    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")
    policy_index = block.index("Mopping requires explicit unattended pet policy")
    turn_on_index = block.index("action: input_boolean.turn_on", policy_index)
    assert "x40_ultra_orchestrated_run_active" in block[turn_on_index : turn_on_index + 150]

    # Cleared on every exit: both the success/incomplete path and the
    # vacuum-skipped path must turn it back off.
    assert block.count("entity_id: input_boolean.x40_ultra_orchestrated_run_active") >= 3


def test_boot_reconciles_orchestrated_run_active_both_ways() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # "id: boot" appears three times: the trigger definition, the
    # already-docked branch, and the still-active branch (in that order).
    boot_positions = [i for i in range(len(block)) if block.startswith("id: boot", i)]
    assert len(boot_positions) == 3

    # Case 1: already docked at boot — clear the now-ambiguous marker
    # alongside the existing stranded-notification clear (Codex's literal
    # suggestion), without guessing at an outcome we can't reconstruct.
    docked_branch = block[boot_positions[1] : boot_positions[1] + 500]
    assert "state: docked" in docked_branch
    assert "x40_ultra_orchestrated_run_active" in docked_branch

    # Case 2: still active at boot — mark interrupted now so the later,
    # genuine dock transition (handled by the existing generic completion
    # branch) reports it accurately.
    still_active_branch = block[boot_positions[2] : boot_positions[2] + 700]
    assert "x40_ultra_orchestrated_run_active" in still_active_branch
    assert "state: \"on\"" in still_active_branch
    assert "cleaning" in still_active_branch and "returning" in still_active_branch and "paused" in still_active_branch
    assert "x40_ultra_orchestrator_interrupted" in still_active_branch


def test_active_run_owned_declared_and_reset_in_both_stage_scripts() -> None:
    # Round 8, Codex P2: x40_ultra_prepare_deterministic_cleaning's
    # documented up-to-30s wait can be won by an external (manual/app) run;
    # when that happens the orchestrator scripts don't start anything, they
    # just wait for that unrelated run to finish, yet the orchestrator script
    # stays "on" throughout — which would mislabel that external run's
    # progress as part of our own two-stage sequence.
    text = VACUUM_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_active_run_owned:" in text

    for script_id in ("x40_ultra_main_level_vacuum_only", "x40_ultra_main_level_mop_only"):
        block = _script_block(VACUUM_PATH, script_id)
        assert "x40_ultra_active_run_owned" in block
        # Reset off near the top, set on only after wait.completed confirms
        # OUR OWN start — not merely that the script ran.
        reset_index = block.index("x40_ultra_active_run_owned")
        wait_completed_index = block.index("wait.completed")
        set_on_index = block.index("x40_ultra_active_run_owned", wait_completed_index)
        assert reset_index < wait_completed_index < set_on_index


def test_live_activity_phase_count_requires_owning_the_active_run() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    two_stage_index = block.index("set two_stage =")
    two_stage_definition = block[two_stage_index : two_stage_index + 250]
    assert "script.x40_ultra_main_level_mop_after_vacuum" in two_stage_definition
    assert "x40_ultra_active_run_owned" in two_stage_definition
