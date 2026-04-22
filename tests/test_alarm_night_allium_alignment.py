from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
IOS_WAKEUP_PATH = ROOT / "packages" / "ios_wakeup.yaml"
MEDIA_PLAYER_PATH = ROOT / "packages" / "media_player.yaml"
TV_PATH = ROOT / "packages" / "tv.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"


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


def test_ios_wakeup_webhook_normalizes_alarm_payload_across_supported_inputs() -> None:
    block = _automation_block(IOS_WAKEUP_PATH, "sync_phone_wakeup_alarm_from_ios_shortcut")

    for token in (
        "trigger.json.alarm_time",
        "trigger.data.alarm_time",
        "trigger.query.alarm_time",
        "trigger.json.alarm_enabled",
        "trigger.data.alarm_enabled",
        "trigger.query.alarm_enabled",
        "{{ raw[0:5] }}",
        "{{ alarm_time_raw != '' }}",
    ):
        assert token in block


def test_phone_alarm_sync_uses_holiday_calendar_to_compute_tomorrow_workday() -> None:
    block = _script_block(WORKDAY_PATH, "set_wakeup_from_phone_alarm")

    for token in (
        "action: calendar.get_events",
        "entity_id: calendar.mn_holidays",
        "tomorrow_is_weekday",
        "tomorrow_is_holiday",
        "tomorrow_is_workday",
        "{{ tomorrow_is_weekday and not tomorrow_is_holiday }}",
    ):
        assert token in block


def test_alarm_spec_documents_today_workday_as_holiday_aware() -> None:
    text = (ROOT / "specs" / "alarm_wakeup.allium").read_text(encoding="utf-8")

    assert "Holiday-aware: true only on a weekday that is not a configured holiday." in text


def test_alarm_wake_up_has_distinct_weekday_weekend_and_meeting_branches() -> None:
    block = _automation_block(WORKDAY_PATH, "alarm_wake_up")

    for trigger_id in ("weekday-alarm", "weekend-alarm", "meeting-alarm"):
        assert f"id: {trigger_id}" in block

    for token in (
        "entity_id: input_boolean.weekday_alarm_on",
        "entity_id: input_boolean.weekend_alarm_on",
        "entity_id: input_boolean.special_meeting",
        "script.sonos_mpr_news_wake_up",
        "script.sonos_the_current_wake_up",
        "script.sonos_ksdj_wake_up",
        "action: input_boolean.turn_off",
        'spotify_uri: "https://open.spotify.com/track/2Mik4RyMTMGXscX9QGiDoX?si=TBH_9RezQA6d1Y1w5iahHQ"',
    ):
        assert token in block

    assert re.search(
        r"action: media_player\.volume_set\s+"
        r"target:\s+"
        r"entity_id:\s+"
        r"- media_player\.bedroom_sonos\s+"
        r"- media_player\.bedroom_sonos_2\s+"
        r"data:\s+"
        r"volume_level: 0\.2",
        block,
    )


def test_snooze_cancel_and_rollover_cover_alarm_followup_semantics() -> None:
    snooze_automation = _automation_block(WORKDAY_PATH, "alarm_snooze")
    cancel_automation = _automation_block(WORKDAY_PATH, "cancel_alarms")
    rollover_automation = _automation_block(WORKDAY_PATH, "turn_off_morning_routine")
    snooze_script = _script_block(WORKDAY_PATH, "snooze_script")

    for token in (
        "entity_id: input_boolean.wakeup_alarm_firing",
        'state: "true"',
        "entity_id: device_tracker.bayesian_zeke_home",
        "entity_id: input_boolean.master_bed_occupancy",
        "entity_id: script.snooze_script",
    ):
        assert token in snooze_automation

    for token in (
        "light.owner_suite_lamps",
        "light.bed_lightstrip",
        "media_player.bedroom_sonos_2",
        "minutes: 8",
        "entity_id: script.wake_up_script",
        "action: media_player.media_play",
    ):
        assert token in snooze_script

    assert "media_player.media_stop" in cancel_automation
    assert "entity_id: media_player.bedroom_sonos_2" in cancel_automation
    assert 'at: "00:00:01"' in rollover_automation
    assert "entity_id: input_boolean.morning_routine" in rollover_automation


def test_bathroom_morning_routine_requires_time_window_and_fresh_state() -> None:
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    for token in (
        "entity_id: binary_sensor.bayesian_bed_occupancy",
        'state: "off"',
        "entity_id: input_boolean.morning_routine",
        'after: "05:00:00"',
        'before: "10:30:00"',
        '- "mon"',
        '- "fri"',
        'after: "07:00:00"',
        'before: "14:00:00"',
        '- "sat"',
        '- "sun"',
    ):
        assert token in block


def test_bathroom_morning_routine_uses_workday_owner_suite_led_policy() -> None:
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    for token in (
        "binary_sensor.workday_sensor",
        "script.apply_owner_suite_inovelli_led_policy",
        "policy: day",
        "scope: bathroom",
        "script.day_mode_switches_office_guest_room",
    ):
        assert token in block

    assert "number.owner_suite_bathroom_vanity_ledintensitywhenoff" not in block


def test_wakeup_audio_uses_guest_aware_sync_groups() -> None:
    spotify_block = _script_block(MEDIA_PLAYER_PATH, "spotify_wake_up")
    radio_block = _script_block(MEDIA_PLAYER_PATH, "music_assistant_radio_wake_up")

    for token in (
        "input_boolean.guest_mode",
        "media_player.guest_sonos",
        "media_player.everywhere_sonos",
        'entity_id: "{{ playback_player }}"',
    ):
        assert token in spotify_block
        assert token in radio_block

    assert "media_player.unjoin" not in spotify_block
    assert "media_player.unjoin" not in radio_block


def test_tv_bed_prep_is_guest_suppressed_and_defers_sleep_mode_shutdown() -> None:
    block = _automation_block(TV_PATH, "tv_off_at_night_bed_prep")

    for token in (
        'after: "20:00:00"',
        'before: "04:00:00"',
        "entity_id: input_boolean.guest_mode",
        "entity_id: binary_sensor.bayesian_bed_occupancy",
        "entity_id: scene.bedroom_prep",
        "entity_id: script.spotify_bedtime",
        'delay: "00:20:00"',
        "entity_id: switch.sleep_mode",
    ):
        assert token in block


def test_bedtime_audio_uses_bathroom_visit_or_timeout_before_rampdown() -> None:
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
        "value_template: \"{{ not guest_context_enabled }}\"",
        "bedroom_audio_pause_targets",
        "'media_player.bedroom_sonos_2'",
        "'media_player.bathroom_sonos_2'",
        "'media_player.office_sonos_2'",
        "'media_player.den_sonos_2'",
        "'media_player.tiki_room_2'",
        "action: media_player.media_pause",
    ):
        assert token in block


def test_goodnight_integrity_verification_checks_guest_sleep_and_away_leakage() -> None:
    block = _script_block(HOUSE_MODE_PATH, "goodnight_integrity")

    for token in (
        "Ecobee is unavailable for bedtime verification.",
        "instead of Guest Sleep.",
        "Ecobee is still in an away preset during bedtime.",
        "states('lock.front_door_lock') != 'locked'",
        "states('cover.garage_door') not in ['closed', 'closing']",
        "states('cover.owner_suite_blinds_ha') not in ['closed', 'closing']",
    ):
        assert token in block
