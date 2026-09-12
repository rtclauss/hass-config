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


def test_live_activity_triggers_on_mode_and_phase_changes() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    assert "entity_id: select.x40_ultra_cleaning_mode" in block
    assert "entity_id: input_boolean.x40_ultra_mop_after_current_pass" in block


def test_live_activity_message_is_phase_aware() -> None:
    block = _automation_block(CLEANING_PATH, "x40_vacuum_live_activity")

    # Distinguishes the two stages by name.
    assert "Mopping" in block
    assert "Vacuuming" in block

    # Only the two-stage vacuum stage is labeled "coming up" (1/2); the mop
    # stage (always stage 2 of 2, since mop_only is never invoked standalone)
    # is labeled (2/2); a single-stage run gets no phase count at all.
    assert "(1/2)" in block
    assert "(2/2)" in block
    assert "two_stage" in block

    # Mop-phase visuals are distinct from the vacuum-phase blue used elsewhere
    # in this same automation (error/complete/vacuum branches).
    assert "mdi:water" in block
    assert "#00ACC1" in block
