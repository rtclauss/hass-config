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


def _zone_script_block(script_id: str) -> str:
    lines = ZONE_PATH.read_text(encoding="utf-8").splitlines()
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


def _scene_block(scene_name: str) -> str:
    lines = ZONE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  - name: {scene_name}"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find scene {scene_name!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - name: "):
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


def test_contextual_arrival_tracks_when_house_becomes_empty() -> None:
    text = ZONE_PATH.read_text(encoding="utf-8")
    block = _automation_block(ZONE_PATH, "input_boolean_tracker_off")

    assert "input_datetime.contextual_arrival_last_empty_at:" in text
    assert "has_date: true" in text
    assert "has_time: true" in text
    assert "event_type: zeke_departure" in block
    assert "source_trigger == 'bayesian_presence_off'" in block
    assert "action: input_boolean.turn_off" in block
    assert "action: input_datetime.set_datetime" in block
    assert "entity_id: input_datetime.contextual_arrival_last_empty_at" in block
    assert "now().strftime('%Y-%m-%d %H:%M:%S')" in block


def test_presence_event_emitters_own_shared_arrival_and_departure_triggers() -> None:
    arrival_emitter = _automation_block(ZONE_PATH, "zeke_arrival_emitter")
    departure_emitter = _automation_block(ZONE_PATH, "zeke_departure_emitter")

    assert "event: enter" in arrival_emitter
    assert "id: tracker_entered_home" in arrival_emitter
    assert "id: bayesian_presence_on" in arrival_emitter
    assert "event: zeke_arrival" in arrival_emitter
    assert "source_trigger: \"{{ trigger.id }}\"" in arrival_emitter

    assert "event: leave" in departure_emitter
    assert "id: tracker_left_home" in departure_emitter
    assert "id: bayesian_presence_off" in departure_emitter
    assert "event: zeke_departure" in departure_emitter
    assert "source_trigger: \"{{ trigger.id }}\"" in departure_emitter


def test_presence_event_consumers_keep_independent_traces_and_modes() -> None:
    arrival_consumers = (
        "cloudy_home_arrival",
        "default_arrive_home",
        "play_spotify_when_i_get_home",
        "turn_on_lights_at_night_when_i_get_home",
        "turn_on_bedroom_lights_at_night_when_i_get_home",
        "vacuum_return_home",
    )
    departure_consumers = (
        "doors_open_when_leaving_home",
        "garage_door_open_when_leaving_home",
        "input_boolean_tracker_off",
        "turn_off_lights_when_i_leave",
        "vacuum_leave_home",
    )

    for automation_id in arrival_consumers:
        block = _automation_block(ZONE_PATH, automation_id)
        trigger_block = block.split("condition:", 1)[0].split("action:", 1)[0]
        assert "trace:" in block
        assert "event_type: zeke_arrival" in trigger_block
        assert "person: zeke" in trigger_block
        assert "event: enter" not in trigger_block
        assert "binary_sensor.bayesian_zeke_home" not in trigger_block

    for automation_id in departure_consumers:
        block = _automation_block(ZONE_PATH, automation_id)
        trigger_block = block.split("condition:", 1)[0].split("action:", 1)[0]
        assert "trace:" in block
        assert "event_type: zeke_departure" in trigger_block
        assert "person: zeke" in trigger_block
        assert "event: leave" not in trigger_block
        assert "binary_sensor.bayesian_zeke_home" not in trigger_block


def test_arrival_automations_use_contextual_arrival_transition() -> None:
    for automation_id in (
        "cloudy_home_arrival",
        "default_arrive_home",
        "turn_on_lights_at_night_when_i_get_home",
        "turn_on_bedroom_lights_at_night_when_i_get_home",
    ):
        block = _automation_block(ZONE_PATH, automation_id)
        assert "action: script.contextual_arrival_transition" in block
        assert "action: script.house_transition" not in block


def test_contextual_arrival_script_tiers_lighting_and_climate_by_absence() -> None:
    block = _zone_script_block("contextual_arrival_transition")

    for threshold in ("3600", "28800", "86400"):
        assert threshold in block

    for tier in ("quick_errand", "half_day", "full_day", "multi_day"):
        assert tier in block

    assert "scene.arrive_home_quick" in block
    assert "scene.night_arrive_home_quick" in block
    assert "scene.arrive_home_full_day" in block
    assert "scene.arrive_home_multi_day" in block
    assert "tier_apply_climate: \"{{ arrival_tier in ['full_day', 'multi_day'] }}\"" in block
    assert "action: script.house_transition" in block
    assert "apply_climate: \"{{ tier_apply_climate }}\"" in block


def test_contextual_arrival_treats_occupied_reentry_as_quick() -> None:
    block = _zone_script_block("contextual_arrival_transition")

    # An established-presence re-entry (Bayesian already "on") must not reuse the
    # stale last_empty timestamp and escalate to full/multi day.
    assert "occupied_reentry" in block
    assert "seconds_since_presence" in block
    assert "is_state('binary_sensor.bayesian_zeke_home', 'on')" in block
    assert "{% if occupied_reentry %}" in block


def test_contextual_arrival_explicit_light_scene_wins_over_tier() -> None:
    block = _zone_script_block("contextual_arrival_transition")

    tier_scene = block.split("tier_light_scene:", 1)[1].split("tier_light_transition:", 1)[0]
    # The caller's explicit scene (e.g. the cloudy bright scene) must be the
    # first branch so absence tiering never discards it.
    first_branch = tier_scene.strip().splitlines()[1].strip()
    assert first_branch == "{% if light_scene is defined and light_scene | string | trim %}"


def test_contextual_arrival_scenes_avoid_guest_private_rooms() -> None:
    for scene_name in (
        "arrive_home_quick",
        "arrive_home_full_day",
        "arrive_home_multi_day",
        "night_arrive_home_quick",
    ):
        block = _scene_block(scene_name)
        assert "light.office" not in block
        assert "light.guest_room" not in block
        assert "media_player." not in block


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
        if in_unjoin and "media_player.ma_den" in stripped:
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
    assert block.count("state_attr('media_player.ma_bedroom', 'group_members') | default([])") >= 2
