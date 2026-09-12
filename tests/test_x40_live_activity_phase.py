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


def test_mop_after_current_pass_helper_declared() -> None:
    text = VACUUM_PATH.read_text(encoding="utf-8")
    assert "x40_ultra_mop_after_current_pass:" in text


def test_vacuum_only_resets_phase_flag_from_two_stage_field_every_call() -> None:
    # The flag must be re-derived from the caller's declared intent on EVERY
    # call (true or false), not only set when true — otherwise a stale "on"
    # from an interrupted two-stage run could leak "mop next" into a later,
    # unrelated single-stage pass (e.g. a segment clean).
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_vacuum_only")

    assert "two_stage" in block
    assert "input_boolean.x40_ultra_mop_after_current_pass" in block

    two_stage_guard_index = block.index("two_stage | default")
    guarded_block = block[two_stage_guard_index:]

    turn_on_index = guarded_block.index("action: input_boolean.turn_on")
    turn_off_index = guarded_block.index("action: input_boolean.turn_off")
    # Both branches of the if/else must target the phase flag, not just one.
    assert "x40_ultra_mop_after_current_pass" in guarded_block[turn_on_index : turn_on_index + 150]
    assert "x40_ultra_mop_after_current_pass" in guarded_block[turn_off_index : turn_off_index + 150]


def test_mop_after_vacuum_passes_two_stage_and_clears_flag_on_every_exit() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_mop_after_vacuum")

    vacuum_call_index = block.index("action: script.x40_ultra_main_level_vacuum_only")
    call_and_data = block[vacuum_call_index : vacuum_call_index + 100]
    assert "two_stage: true" in call_and_data

    # The flag must be cleared after the if/else that decides mop-or-skip, so
    # it is cleared regardless of which branch ran (mop launched, or skipped
    # because the vacuum pass did not complete cleanly).
    else_index = block.index("else:")
    final_turnoff_index = block.rindex("action: input_boolean.turn_off")
    final_turnoff_block = block[final_turnoff_index : final_turnoff_index + 150]

    assert final_turnoff_index > else_index, (
        "the phase-flag cleanup must come after the mop-or-skip branch, not before it"
    )
    assert "x40_ultra_mop_after_current_pass" in final_turnoff_block


def test_segment_vacuum_only_resets_phase_flag_unconditionally() -> None:
    # A segment clean never mops. Codex P2: this script never touched the
    # flag, so a stale "on" left behind by an interrupted two-stage
    # main-level run would mislabel an unrelated segment pass as
    # "Vacuuming (1/2)".
    block = _script_block(VACUUM_PATH, "x40_ultra_segment_vacuum_only")

    turnoff_index = block.index("action: input_boolean.turn_off")
    assert "x40_ultra_mop_after_current_pass" in block[turnoff_index : turnoff_index + 150]

    # Must reset before the at-rest gate, i.e. on every call, not only when
    # the robot happens to be at rest.
    gate_index = block.index("X40 must be at rest before any deterministic mutation")
    assert turnoff_index < gate_index


def test_phase_flag_forced_off_on_every_restart() -> None:
    # Codex P2: no in-flight two-stage sequence survives an HA restart (the
    # orchestrating script is gone), so restoring a stale "on" would
    # misreport a mop as still queued when it will not actually resume.
    text = VACUUM_PATH.read_text(encoding="utf-8")
    flag_index = text.index("x40_ultra_mop_after_current_pass:")
    declaration = text[flag_index : flag_index + 400]
    assert "initial: false" in declaration


def test_live_activity_completion_branch_skips_interim_dock() -> None:
    # Codex P2: without this guard, the interim dock between the two stages
    # of a vacuum-then-mop run posted a false "Cleaning complete" and (since
    # this automation is mode: queued) its 2-minute delay blocked the
    # subsequent "Mopping (2/2)" update behind it.
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # Use the actual message key, not the bare phrase: an earlier code
    # comment on this same branch already mentions "Cleaning complete" in
    # prose, which would otherwise match first.
    complete_index = block.index("message: Cleaning complete")
    preceding = block[:complete_index]
    not_index = preceding.rindex("condition: not")
    guarded = preceding[not_index:]

    # HA's `not` condition is a logical NOR across its list, so negating a
    # two-clause AND requires nesting an explicit `and`, not two bare
    # siblings under `not` (which would require BOTH to be false to pass).
    assert "condition: and" in guarded
    assert "input_boolean.x40_ultra_mop_after_current_pass" in guarded
    assert "select.x40_ultra_cleaning_mode" in guarded
    assert 'state: "on"' in guarded
    assert 'state: "sweeping"' in guarded


def test_live_activity_mopping_label_gated_on_two_stage_flag() -> None:
    # Codex P2: a standalone/manual mop (started directly, or from the
    # Dreame app) is not part of an orchestrated two-stage run, so it must
    # not be labeled "(2/2)" — only a genuine two-stage run (flag on) earns
    # the phase count; otherwise it's plain "Mopping".
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert "'mopping' and two_stage %}Mopping{{ rs }} (2/2)" in block
    assert "elif mode == 'mopping'\n" in block


def test_live_activity_triggers_on_mode_and_phase_changes() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert "entity_id: select.x40_ultra_cleaning_mode" in block
    assert "entity_id: input_boolean.x40_ultra_mop_after_current_pass" in block


def test_live_activity_message_is_phase_aware() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # Distinguishes the two stages by name.
    assert "Mopping" in block
    assert "Vacuuming" in block

    # A phase count is only shown while the two-stage flag is actually on;
    # a single-stage run (vacuum or mop) gets no phase count at all.
    assert "(1/2)" in block
    assert "(2/2)" in block
    assert "two_stage" in block

    # Mop-phase visuals are distinct from the vacuum-phase blue used elsewhere
    # in this same automation (error/complete/vacuum branches).
    assert "mdi:water" in block
    assert "#00ACC1" in block
