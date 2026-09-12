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


def test_live_activity_triggers_on_mode_and_orchestrator_state() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert "entity_id: select.x40_ultra_cleaning_mode" in block
    assert "entity_id: script.x40_ultra_main_level_mop_after_vacuum" in block
    assert "input_boolean.x40_ultra_mop_after_current_pass" not in block


def test_live_activity_completion_branch_skips_interim_dock() -> None:
    # Skip the false "Cleaning complete" on the interim dock between the two
    # stages of a vacuum-then-mop run (orchestrator still running + mode
    # still "sweeping") — the genuine final dock (mode already "mopping")
    # still reaches this branch normally.
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
    assert "script.x40_ultra_main_level_mop_after_vacuum" in guarded
    assert "select.x40_ultra_cleaning_mode" in guarded
    assert 'state: "on"' in guarded
    assert 'state: "sweeping"' in guarded


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
