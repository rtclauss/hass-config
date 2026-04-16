from __future__ import annotations

import re
from pathlib import Path


HOUSE_MODE_PATH = Path(__file__).resolve().parents[1] / "packages" / "house_mode.yaml"
ZONE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zone.yaml"


def _script_block(script_id: str) -> str:
    lines = HOUSE_MODE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
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


def test_house_transition_no_longer_queues_later_mode_changes() -> None:
    text = _script_block("house_transition")

    assert "house_transition:" in text
    assert "mode: restart" in text
    assert "script.lights_off_except" in text
    assert "continue_on_error: true\n        action: logbook.log" in text


def test_house_transition_supports_in_bed_and_asleep_without_forcing_night_scene_defaults() -> None:
    text = HOUSE_MODE_PATH.read_text(encoding="utf-8")
    block = _script_block("house_transition")

    for token in (
        "- in_bed",
        "- asleep",
        "House mode to apply: home, away, night, in_bed, or asleep.",
        "normalized in ['away', 'night', 'in_bed', 'asleep']",
        "requested_mode in ['home', 'night', 'in_bed', 'asleep']",
    ):
        assert token in text or token in block

    assert "elif requested_mode == 'night'" in block
    assert "resolved_light_scene" in block


def test_departure_house_transition_runs_in_parallel_without_embedding_vacuum_logic() -> None:
    transition_block = _automation_block(ZONE_PATH, "turn_off_lights_when_i_leave")
    vacuum_block = _automation_block(ZONE_PATH, "vacuum_leave_home")

    assert "parallel:" in transition_block
    assert "action: script.house_transition" in transition_block
    assert "action: mqtt.publish" not in transition_block
    assert "action: script.vacuum_main_and_upstairs_levels" not in transition_block
    assert "action: script.vacuum_main_and_upstairs_levels" in vacuum_block


def test_departure_waits_for_primary_tracker_to_leave_home() -> None:
    block = _automation_block(ZONE_PATH, "turn_off_lights_when_i_leave")

    assert "Primary tracker confirms departure" in block
    assert "device_tracker.bayesian_zeke_home" in block
    assert "not is_state('device_tracker.bayesian_zeke_home', 'home')" in block


def test_house_transition_guest_mode_grouping_never_unjoins_den() -> None:
    block = _script_block("house_transition")

    # den_sonos_2 must not appear in any unjoin target — it is the Den Turntable
    # line-in recipient and disrupting it via a mode transition would cut off
    # turntable audio unexpectedly.
    lines = block.splitlines()
    in_unjoin = False
    for line in lines:
        stripped = line.strip()
        if stripped == "action: media_player.unjoin":
            in_unjoin = True
        elif in_unjoin and stripped.startswith("action:"):
            in_unjoin = False
        if in_unjoin and "media_player.den_sonos_2" in stripped:
            raise AssertionError(
                "house_transition unjoins den_sonos_2 — this disrupts the Den Turntable"
            )


def test_house_transition_media_grouping_is_idempotent() -> None:
    block = _script_block("house_transition")

    # Both guest-mode and non-guest-mode branches must guard against redundant
    # unjoin/rejoin cycles so repeated house_transition calls are safe.
    # Must use if/then (not stop:) so parallel branches and the post-parallel
    # notification step are never skipped.
    assert "Reform guest-mode group only if not already correctly formed" in block
    assert "Reform full group only if not already correctly formed" in block
    assert "stop:" not in block
    assert block.count("state_attr('media_player.bedroom_sonos_2', 'group_members') | default([])") >= 2
