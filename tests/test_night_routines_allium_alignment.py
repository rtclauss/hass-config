from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
MEDIA_PLAYER_PATH = ROOT / "packages" / "media_player.yaml"
TV_PATH = ROOT / "packages" / "tv.yaml"


def _script_block(path: Path, script_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r} in {path.name}")

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


def test_tv_bed_prep_supports_television_shutdown_and_button_entrypoints() -> None:
    block = _automation_block(TV_PATH, "tv_off_at_night_bed_prep")

    for token in (
        'entity_id: media_player.lg_webos_smart_tv',
        'from: "on"',
        'to: "off"',
        'to: "unavailable"',
        'from: "off"',
        "event_type: zha_event",
        'device_ieee: "00:15:8d:00:02:12:fc:ff"',
        'command: "attribute_updated"',
        "entity_id:\n          - sensor.hall_button_action",
        'to: "single"',
    ):
        assert token in block


def test_tv_bed_prep_handles_off_to_unavailable_shutdown_handoff() -> None:
    block = _automation_block(TV_PATH, "tv_off_at_night_bed_prep")

    assert 'from: "off"\n        to: "unavailable"' in block
    assert "seconds: 10" in block


def test_tv_bed_prep_requires_night_window_no_guest_mode_and_not_in_bed() -> None:
    block = _automation_block(TV_PATH, "tv_off_at_night_bed_prep")

    for token in (
        'after: "20:00:00"',
        'before: "04:00:00"',
        "entity_id: input_boolean.guest_mode",
        'state: "off"',
        "entity_id: binary_sensor.bayesian_bed_occupancy",
    ):
        assert token in block


def test_tv_bed_prep_starts_low_volume_bedroom_prep_and_delayed_sleep_mode_release() -> None:
    block = _automation_block(TV_PATH, "tv_off_at_night_bed_prep")

    for token in (
        "entity_id:\n            - media_player.bedroom_sonos_2\n            - media_player.bathroom_sonos_2",
        "volume_level: 0.02",
        "entity_id: scene.bedroom_prep",
        "entity_id: script.spotify_bedtime",
        'delay: "00:20:00"',
        "entity_id: switch.sleep_mode",
    ):
        assert token in block


def test_spotify_bedtime_uses_bathroom_visit_or_timeout_before_rampdown() -> None:
    block = _script_block(MEDIA_PLAYER_PATH, "spotify_bedtime")

    for token in (
        "wait_for_trigger:",
        "entity_id: binary_sensor.owner_suite_bathroom_room_occupancy",
        'to: "on"',
        "minutes: 10",
        "continue_on_timeout: true",
        'value_template: "{{ wait.completed }}"',
        "minutes: 3",
        "target:\n          entity_id: script.spotify_bedtime_volume",
        "entity_id: script.spotify_bedtime_volume",
    ):
        assert token in block


def test_goodnight_integrity_preserves_bedroom_audio_and_pauses_unrelated_rooms() -> None:
    block = _script_block(HOUSE_MODE_PATH, "goodnight_integrity")

    for token in (
        "script.house_transition",
        "mode: asleep",
        'value_template: "{{ not guest_context_enabled }}"',
        "bedroom_audio_pause_targets",
        "'media_player.bedroom_sonos_2'",
        "'media_player.bathroom_sonos_2'",
        "'media_player.office_sonos_2'",
        "'media_player.den_sonos_2'",
        "'media_player.tiki_room_2'",
        'value_template: "{{ bedroom_audio_pause_targets | trim != \'\' }}"',
        "action: media_player.media_pause",
        'entity_id: "{{ bedroom_audio_pause_targets }}"',
    ):
        assert token in block


def test_goodnight_integrity_verifies_guest_sleep_and_away_preset_exceptions() -> None:
    block = _script_block(HOUSE_MODE_PATH, "goodnight_integrity")

    for token in (
        "state_attr('climate.my_ecobee', 'preset_mode') != 'Guest Sleep'",
        "instead of Guest Sleep.",
        "state_attr('climate.my_ecobee', 'preset_mode') in ['Away', 'away', 'away_indefinitely']",
        "Ecobee is still in an away preset during bedtime.",
    ):
        assert token in block


def test_night_routines_spec_owns_owner_suite_led_policy_enum() -> None:
    text = (ROOT / "specs" / "night_routines.allium").read_text(encoding="utf-8")

    for token in (
        "enum OwnerSuiteSwitchLedMode { dark | night_red | day }",
        "owner_suite_switch_led_mode: OwnerSuiteSwitchLedMode",
        "ensures: house.owner_suite_switch_led_mode = dark",
        "rule RestoreOwnerSuiteSwitchLedsToNightRed",
        "rule ApplyOwnerSuiteWorkdayMorningLedPolicy",
        "today_is_workday is holiday-aware",
        "rule KeepOwnerSuiteSwitchLedsDarkOnNonWorkdayMornings",
    ):
        assert token in text
