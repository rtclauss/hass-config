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

    # Use the actual message key, not the bare phrase: an earlier code
    # comment on this same branch already mentions "Cleaning complete" in
    # prose, which would otherwise match first.
    complete_index = block.index("message: Cleaning complete")
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

    # "id: orchestrator_end" appears twice: once defining the trigger, once
    # referencing it in the choose branch's conditions — use the LATTER
    # (the branch that actually finalizes the notification).
    branch_index = block.rindex("id: orchestrator_end")
    finalize_section = block[branch_index : branch_index + 400]
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
