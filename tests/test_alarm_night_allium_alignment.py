from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
IOS_WAKEUP_PATH = ROOT / "packages" / "ios_wakeup.yaml"
MEDIA_PLAYER_PATH = ROOT / "packages" / "media_player.yaml"
TV_PATH = ROOT / "packages" / "tv.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
ALARM_SPEC_PATH = ROOT / "specs" / "alarm_wakeup.allium"


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
    text = ALARM_SPEC_PATH.read_text(encoding="utf-8")

    assert "Holiday-aware: true only on a weekday that is not a configured holiday." in text


def test_bed_strip_automatic_cap_matches_wakeup_ramp_and_reconciliation() -> None:
    spec_text = ALARM_SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"bed_strip_automatic_max_brightness_percent: Integer = (\d+)",
        spec_text,
    )

    assert match is not None
    cap = match.group(1)
    wakeup_transition = _script_block(WORKDAY_PATH, "owner_suite_morning_transition")
    adaptive_package = (ROOT / "packages" / "adaptive_lighting.yaml").read_text(
        encoding="utf-8"
    )

    assert f"bed_strip_automatic_max_brightness_percent: {cap}" in wakeup_transition
    assert f"bed_strip_automatic_max_brightness_percent: {cap}" in adaptive_package
    assert "owner_suite.bed_strip_brightness_percent = bed_strip_wake_target_percent" in spec_text
    assert "Direct resident" in spec_text


def test_wakeup_office_volume_caps_match_allium_peak() -> None:
    spec_text = ALARM_SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"office_wakeup_peak_volume_percent: Integer = (\d+)", spec_text)

    assert match is not None
    cap = f"0.{int(match.group(1)):02d}"
    radio_wakeup = _script_block(MEDIA_PLAYER_PATH, "music_assistant_radio_wake_up")
    bathroom_followup = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    assert "config.office_wakeup_peak_volume" in spec_text
    assert radio_wakeup.count(f"default({cap}) | float({cap})") == 1
    assert bathroom_followup.count(f", {cap}] | min") == 2


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
        r"entity_id: media_player\.ma_bedroom\s+"
        r"data:\s+"
        r"volume_level: 0\.2",
        block,
    )


def test_weekday_alarm_runs_when_it_is_before_meeting_reminder() -> None:
    spec_text = (ROOT / "specs" / "alarm_wakeup.allium").read_text(encoding="utf-8")
    block = _automation_block(WORKDAY_PATH, "alarm_wake_up")

    assert "or wakeup.weekday_alarm_time < wakeup.next_work_meeting_alarm_time" in spec_text

    for token in (
        "condition: or",
        "weekday alarm is before meeting reminder",
        "state_attr('input_datetime.weekday_alarm', 'timestamp') | int(0)",
        "state_attr('input_datetime.next_work_meeting', 'timestamp') | int(0)",
        "weekday_alarm_timestamp < meeting_alarm_timestamp",
    ):
        assert token in block


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
        "media_player.ma_bedroom",
        "minutes: 8",
        "entity_id: script.wake_up_script",
        "action: media_player.media_play",
    ):
        assert token in snooze_script

    assert "media_player.media_stop" in cancel_automation
    assert "entity_id: media_player.ma_bedroom" in cancel_automation
    assert 'at: "00:00:01"' in rollover_automation
    assert "entity_id: input_boolean.morning_routine" in rollover_automation


def test_bathroom_morning_routine_requires_time_window_and_fresh_state() -> None:
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    for token in (
        "entity_id: binary_sensor.bayesian_bed_occupancy",
        'state: "off"',
        "entity_id: input_boolean.morning_routine",
        "input_datetime.weekday_alarm",
        "input_datetime.weekend_alarm",
        "input_boolean.weekday_alarm_on",
        "input_boolean.weekend_alarm_on",
        "wake_window_seconds = 90 * 60",
    ):
        assert token in block


def test_bathroom_morning_routine_only_fires_within_the_real_alarm_window() -> None:
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    # input_datetime.weekday_alarm/weekend_alarm are has_date: false, so their
    # timestamp attribute is seconds since midnight (confirmed live:
    # 07:30:00 -> 27000), not a Unix epoch value. Comparing that against
    # now().timestamp() (~1.8 billion) made the window condition permanently
    # false (Codex P1 on #972) — must compare seconds-since-midnight against
    # seconds-since-midnight, matching the pattern workday.yaml already uses
    # for the same alarm helpers (#939).
    assert "now().timestamp() >=" not in block
    assert "now().timestamp() <=" not in block
    assert "now_seconds_since_midnight = now().hour * 3600 + now().minute * 60 + now().second" in block
    assert "now_seconds_since_midnight >= alarm_seconds_since_midnight" in block
    assert "now_seconds_since_midnight <= (alarm_seconds_since_midnight + wake_window_seconds)" in block
    assert "alarm_enabled and alarm_seconds_since_midnight > 0" in block
    # The old fixed 5:00-10:30 / 7:00-14:00 windows must be gone — a bathroom
    # trip before today's alarm (e.g. waking early, going back to bed) should
    # no longer be enough on its own to start wake-up music.
    assert 'after: "05:00:00"' not in block
    assert 'before: "10:30:00"' not in block


def test_bathroom_morning_routine_alarm_window_includes_special_meeting() -> None:
    # Codex P2 on #972: alarm_wake_up's meeting-alarm branch can wake the
    # resident via input_datetime.next_work_meeting earlier than the
    # weekday alarm when input_boolean.special_meeting is on. The window
    # must consider both candidates and use the earliest, mirroring
    # workday_owner_suite_wake_transition_from_morning_activity (#939).
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    for token in (
        "input_datetime.next_work_meeting",
        "input_boolean.special_meeting",
        "select('number') | reject('equalto', 0) | list",
        "candidates | min if candidates else 0",
    ):
        assert token in block


def test_bathroom_morning_routine_falls_back_to_wakeup_alarm_firing() -> None:
    # Codex P2 follow-up on #972: alarm_wake_up's meeting-alarm branch turns
    # special_meeting off the instant it fires, before the resident can
    # reach the bathroom, so the candidate list above no longer sees it by
    # the time this template re-evaluates. wakeup_alarm_firing is a durable
    # signal that some alarm fired, used as a fallback alongside the
    # timestamp window.
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    assert "alarm_firing_recently = is_state('input_boolean.wakeup_alarm_firing', 'on')" in block
    or_index = block.index("alarm_firing_recently\n")
    or_clause_index = block.index(" or (alarm_enabled", or_index)
    assert or_clause_index > or_index


def test_bathroom_morning_routine_bounds_the_firing_fallback_to_the_window() -> None:
    # Codex P1 follow-up on #972: turn_off_alarm_firing (packages/light.yaml)
    # only clears wakeup_alarm_firing at a fixed 14:34:56, not on cancel or
    # after any reasonable delay — an unbounded OR on its raw state reopened
    # essentially the original unbounded-window bug for hours after an early
    # alarm. Must be bounded to the same wake_window_seconds.
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    assert (
        "as_timestamp(now()) - (state_attr('input_datetime.wakeup_alarm_fired_at', 'timestamp')"
        in block
    )
    assert "float(0))) <= wake_window_seconds" in block


def test_bathroom_morning_routine_firing_fallback_survives_a_restart() -> None:
    # Codex P2 follow-up on #972: input_boolean state is restored across an
    # HA restart, but the restored entity gets a fresh last_changed at
    # restore time, not the original fire time — a restart while an alarm
    # was still "firing" would look like a brand new alarm just fired.
    # Must use the explicit, restart-safe input_datetime.wakeup_alarm_
    # fired_at instead of wakeup_alarm_firing's own last_changed.
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    assert "input_datetime.wakeup_alarm_fired_at" in block
    assert "states.input_boolean.wakeup_alarm_firing.last_changed" not in block


def test_bathroom_morning_routine_disables_window_on_unavailable_workday_sensor() -> None:
    # Codex P2 follow-up on #972: alarm_wake_up requires binary_sensor.
    # workday_sensor to be explicitly "on" (weekday branch) or explicitly
    # "off" (weekend branch); an unknown/unavailable state (e.g. during
    # startup) satisfies neither, so no real alarm can fire. is_state(...,
    # 'on') alone can't distinguish "off" from "unknown"/"unavailable" —
    # both just aren't "on" — so this used to fall through to the weekend
    # path and could still open a window off a persistent weekend alarm
    # even though alarm_wake_up itself stays silent. Must require an exact
    # 'off' match for the weekend path too, and disable the window entirely
    # otherwise.
    block = _automation_block(MEDIA_PLAYER_PATH, "play_music_in_bathroom_when_up")

    assert "workday_sensor_state = states('binary_sensor.workday_sensor')" in block
    assert "{% if workday_sensor_state == 'on' %}" in block
    assert "{% elif workday_sensor_state == 'off' %}" in block
    assert "{% set alarm_enabled = false %}" in block
    assert "{% set alarm_seconds_since_midnight = 0 %}" in block


def test_wake_up_script_records_the_alarm_fire_time_explicitly() -> None:
    block = _script_block(WORKDAY_PATH, "wake_up_script")

    assert "entity_id: input_datetime.wakeup_alarm_fired_at" in block
    turn_on_index = block.index("entity_id: input_boolean.wakeup_alarm_firing")
    set_datetime_index = block.index("entity_id: input_datetime.wakeup_alarm_fired_at")
    assert set_datetime_index > turn_on_index


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


def test_wakeup_audio_uses_exact_guest_aware_wake_group() -> None:
    spotify_block = _script_block(MEDIA_PLAYER_PATH, "spotify_wake_up")
    radio_block = _script_block(MEDIA_PLAYER_PATH, "music_assistant_radio_wake_up")
    prime_group_block = _script_block(MEDIA_PLAYER_PATH, "music_assistant_prime_wake_group")

    assert "input_boolean.guest_mode" in spotify_block
    assert "input_boolean.guest_mode" in radio_block
    for block in (spotify_block, radio_block):
        assert "media_player.ma_bedroom" in block
        assert "media_player.ma_bathroom" in block
        assert "media_player.ma_office" in block
        assert "media_player.ma_den" in block
        assert "media_player.ma_group_guest" not in block
        assert "media_player.ma_group_everywhere" not in block
        assert "media_player.ma_tiki_room" not in block
        assert "script.music_assistant_prime_wake_group" in block

    for token in ("media_player.volume_set", "media_player.join"):
        assert token in prime_group_block
    assert "media_player.ma_bedroom" in prime_group_block
    assert "media_player.ma_tiki_room" not in prime_group_block

    # Both play through the bedroom MA player after preparing the exact
    # policy wake group; the radio wake-up routes playback through the source helper.
    assert 'entity_id: "{{ playback_player }}"' in spotify_block
    assert 'target_entity: "{{ playback_player }}"' in radio_block

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
        "'media_player.ma_bedroom'",
        "'media_player.ma_bathroom'",
        "'media_player.ma_office'",
        "'media_player.ma_den'",
        "'media_player.ma_tiki_room'",
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
