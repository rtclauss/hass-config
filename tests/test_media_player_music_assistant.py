from __future__ import annotations

import re
from pathlib import Path


MEDIA_PLAYER_PATH = Path(__file__).resolve().parents[1] / "packages" / "media_player.yaml"
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / ".storage" / "lovelace.ryan_new_mushroom"


def _script_block(script_id: str) -> str:
    lines = MEDIA_PLAYER_PATH.read_text(encoding="utf-8").splitlines()
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


def _automation_block(automation_id: str) -> str:
    lines = MEDIA_PLAYER_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  - id: {automation_id}"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find automation id {automation_id!r}")

    end = len(lines)
    next_automation = re.compile(r"^  - id: ")
    for index in range(start + 1, len(lines)):
        if next_automation.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def test_music_assistant_item_helper_normalizes_spotify_uris() -> None:
    block = _script_block("music_assistant_play_item")

    assert "Music Assistant URI, open.spotify.com URL, or plain item name" in block
    assert "raw_media_type" in block
    assert "music_assistant.play_media" in block
    # Must NOT pin a Spotify provider-instance id: it changes on every MA
    # re-onboard and goes stale (see docs/music_assistant.md). Use bare spotify: URIs.
    assert "spotify--" not in block
    # Still normalizes spotify:user:<u>:playlist:<id> -> bare spotify:playlist:<id>
    assert "raw_item.startswith('spotify:user:')" in block
    assert "raw_item.startswith('https://open.spotify.com/')" not in block


def test_music_assistant_search_helpers_populate_dashboard_results() -> None:
    block = _script_block("music_assistant_search_music")

    for token in (
        "input_text.music_assistant_search_query",
        "input_select.music_assistant_provider_filter",
        "input_select.music_assistant_search_media_type",
        "input_select.music_assistant_search_results",
        "config_entry_id('media_player.bedroom_sonos_2')",
        "music_assistant.search",
        "Direct URI ||",
        "provider_tokens",
        "All providers",
        "No results found",
    ):
        assert token in block


def test_music_assistant_selected_result_can_be_added_to_playlist_targets() -> None:
    block = _script_block("music_assistant_add_selected_search_result_to_playlist")

    for token in (
        "input_select.music_assistant_search_results",
        "input_select.music_assistant_playlist_target",
        "selected_option.split(' || ', 1)[1]",
        "target_option.split(' || ', 1)[1]",
        "shell_command.music_assistant_append_playlist_item",
        "script.reload",
    ):
        assert token in block


def test_music_assistant_selected_result_can_be_queued_or_played() -> None:
    block = _script_block("music_assistant_play_selected_search_result")

    for token in (
        "input_select.music_assistant_search_results",
        "selected_option.split(' || ', 1)[1]",
        "script.music_assistant_play_item",
        "media_player.bedroom_sonos_2",
    ):
        assert token in block

    assert "enqueue: \"{{ enqueue | default('add') }}\"" in block


def test_spotify_wrapper_delegates_to_generic_music_assistant_helper() -> None:
    block = _script_block("music_assistant_play_spotify_uri")

    assert "action: script.music_assistant_play_item" in block
    assert "normalized_uri" in block
    assert "open.spotify.com" in block
    assert 'media_item: "{{ normalized_uri }}"' in block


def test_bedroom_playlist_helper_logs_and_plays_selected_playlist() -> None:
    block = _script_block("music_assistant_play_bedroom_playlist_choice")

    for token in (
        "playlist:",
        "playlist_name:",
        "Cube Playlist is",
        "media_player.bedroom_sonos_2",
        "script.music_assistant_play_spotify_uri",
        'spotify_uri: "{{ playlist }}"',
    ):
        assert token in block


def test_random_lofi_helper_centralizes_sleep_safe_playlist_pool() -> None:
    block = _script_block("music_assistant_play_random_lofi_playlist")

    for token in (
        "media_player.bedroom_sonos_2",
        "spotify:playlist:6VHsDUVy0Hj79qMvOohTKV",
        "spotify:playlist:37i9dQZF1DX8Uebhn9wzrS",
        "spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
        "spotify:playlist:37i9dQZF1DX4nNmLlb3JR2",
        "range(0, (plists | length))",
        "action: script.music_assistant_play_spotify_uri",
        'entity_id: "{{ playback_entity }}"',
        'spotify_uri: "{{ playlist }}"',
    ):
        assert token in block


def test_house_party_helper_is_stubbed_after_sync_group_migration() -> None:
    block = _script_block("music_assistant_prepare_house_party_group")
    common_block = _script_block("music_assistant_sync_group_migration_stub")

    assert "script.music_assistant_sync_group_migration_stub" in block
    assert "caller_entity_id: script.music_assistant_prepare_house_party_group" in block
    assert "Sync Group Migration" in common_block
    assert "targeting sync groups directly now" in common_block
    assert "action: media_player.join" not in block


def test_bedroom_group_helper_is_restartable_migration_stub() -> None:
    block = _script_block("music_assistant_prepare_bedroom_group")
    common_block = _script_block("music_assistant_sync_group_migration_stub")

    assert 'mode: restart' in block
    assert "script.music_assistant_sync_group_migration_stub" in block
    assert "caller_entity_id: script.music_assistant_prepare_bedroom_group" in block
    assert "Sync Group Migration" in common_block
    assert "targeting sync groups directly now" in common_block
    assert "action: media_player.unjoin" not in block


def test_arrival_group_helper_is_stubbed_after_sync_group_migration() -> None:
    block = _script_block("music_assistant_prepare_arrival_group")
    common_block = _script_block("music_assistant_sync_group_migration_stub")

    assert "script.music_assistant_sync_group_migration_stub" in block
    assert "caller_entity_id: script.music_assistant_prepare_arrival_group" in block
    assert "Sync Group Migration" in common_block
    assert "targeting sync groups directly now" in common_block
    assert "action: media_player.unjoin" not in block


def test_arrival_music_targets_guest_aware_sync_group_without_regroup_retry() -> None:
    arrival_block = _script_block("spotify_arrival")

    assert "media_player.ma_group_guest" in arrival_block
    assert "media_player.ma_group_everywhere" in arrival_block
    assert "input_boolean.guest_mode" in arrival_block
    assert 'action: script.music_assistant_play_spotify_uri' in arrival_block
    assert 'action: script.music_assistant_prepare_arrival_group' not in arrival_block
    assert 'entity_id: script.music_assistant_try_join_arrival_group_after_play' not in arrival_block


def test_arrival_music_sets_volume_on_selected_music_assistant_group_members() -> None:
    arrival_block = _script_block("spotify_arrival")

    assert "arrival_volume_entities" in arrival_block
    assert "'media_player.ma_group_guest' if is_state('input_boolean.guest_mode', 'on')" in arrival_block
    assert "if is_state('input_boolean.guest_mode', 'on')" in arrival_block
    assert "entity_id: \"{{ arrival_volume_entities }}\"" in arrival_block

    guest_volume_start = arrival_block.index("arrival_volume_entities")
    everywhere_volume_start = arrival_block.index("else [", guest_volume_start)

    guest_volume_block = arrival_block[guest_volume_start:everywhere_volume_start]
    everywhere_volume_block = arrival_block[everywhere_volume_start:arrival_block.index("sequence:")]

    for entity_id in (
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
    ):
        assert entity_id in guest_volume_block
        assert entity_id in everywhere_volume_block

    for guest_private_entity_id in (
        "media_player.den_sonos_2",
        "media_player.office_sonos_2",
        "media_player.tiki_room_2",
    ):
        assert guest_private_entity_id not in guest_volume_block
        assert guest_private_entity_id in everywhere_volume_block

    for entity_id in (
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
        "media_player.den_sonos_2",
        "media_player.office_sonos_2",
        "media_player.tiki_room_2",
    ):
        assert entity_id in arrival_block

    for stale_entity_id in (
        "media_player.bedroom_sonos",
        "media_player.den_sonos",
        "media_player.office_sonos",
        "media_player.tiki_room_3",
    ):
        assert (
            re.search(rf"^\s*-\s+{re.escape(stale_entity_id)}\s*$", arrival_block, re.MULTILINE)
            is None
        )


def test_bedtime_targets_guest_aware_sync_group_before_playing() -> None:
    block = _script_block("spotify_bedtime")

    assert "bedtime_playback_entity" in block
    assert "media_player.ma_group_guest" in block
    assert "media_player.ma_group_everywhere" in block
    assert "input_boolean.guest_mode" in block
    assert 'action: script.music_assistant_prepare_bedroom_group' not in block
    assert 'action: script.music_assistant_play_item' in block
    assert block.index("media_player.ma_group_guest") < block.index(
        'action: script.music_assistant_play_item'
    )


def test_bedtime_join_retry_helper_is_stubbed_after_sync_group_migration() -> None:
    helper_block = _script_block("music_assistant_try_join_bedroom_group_after_play")
    common_block = _script_block("music_assistant_sync_group_migration_stub")
    bedtime_block = _script_block("spotify_bedtime")

    assert 'mode: restart' in helper_block
    assert "script.music_assistant_sync_group_migration_stub" in helper_block
    assert "caller_entity_id: script.music_assistant_try_join_bedroom_group_after_play" in helper_block
    assert "Sync Group Migration" in common_block
    assert "targeting sync groups directly now" in common_block
    assert 'entity_id: script.music_assistant_try_join_bedroom_group_after_play' not in bedtime_block


def test_radio_wakeup_prepares_exact_guest_aware_wake_group() -> None:
    block = _script_block("music_assistant_radio_wake_up")

    assert 'playback_entity_id:' in block
    assert 'regroup_after_play:' in block
    assert 'playback_player: media_player.bedroom_sonos_2' in block
    assert 'input_boolean.guest_mode' in block
    assert 'prepare_group_before_play:' not in block
    assert 'should_prepare_group_before_play' not in block
    assert 'should_regroup_after_play' not in block
    assert 'action: media_player.unjoin' not in block
    assert 'action: script.music_assistant_prepare_bedroom_group' not in block
    assert 'action: media_player.join' not in block
    assert 'action: script.music_assistant_prime_wake_group' in block
    assert 'starting_volume: 0.01' in block
    # Playback is routed through the source helper after preparing the exact group.
    assert 'target_entity: "{{ playback_player }}"' in block
    assert 'entity_id: script.music_assistant_try_join_bedroom_group_after_play' not in block
    assert 'media_player.tiki_room_2' not in block


def test_radio_wakeup_ramps_policy_wake_group_members_not_whole_house_group() -> None:
    block = _script_block("music_assistant_radio_wake_up")

    # Volume operations target exact MA Sonos members, not the mutable
    # whole-house MA sync group whose membership can include unrelated rooms.
    assert len(re.findall(r"^\s+- media_player\.bedroom_sonos$", block, re.MULTILINE)) == 0
    assert len(re.findall(r"^\s+- media_player\.bathroom_sonos$", block, re.MULTILINE)) == 0
    for entity_id in (
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
        "media_player.office_sonos_2",
        "media_player.den_sonos_2",
    ):
        assert entity_id in block
    assert "media_player.ma_group_everywhere" not in block
    assert "media_player.ma_group_guest" not in block
    assert "media_player.tiki_room_2" not in block
    assert block.count('target_entity: "{{ playback_player }}"') >= 1
    assert 'group_members: "{{ group_members }}"' in block
    assert 'volume_level: "{{ 0.01 * repeat.index }}"' in block


def test_radio_wakeup_verifies_retries_and_falls_back_before_ramp() -> None:
    block = _script_block("music_assistant_radio_wake_up")

    # Verification + recovery must precede the volume ramp so a silent group is
    # never reported as a successful wake-up (issue #772).
    for token in (
        "pre_playback_fingerprint",
        "effective_fallback_uri",
        "fallback_media_type",
        "effective_retry_backoff",
        "persistent_notification.create",
        "wakeup_radio_failed",
        "logbook.log",
        "error: true",
        "skipped volume ramp",
    ):
        assert token in block, token

    # Primary, retry, and fallback all play via the source helper (which itself
    # picks media_player.play_media for raw URLs vs music_assistant.play_media
    # for MA URIs — see test_play_wakeup_source_branches_url_vs_ma_uri).
    assert block.count("action: script.music_assistant_play_wakeup_source") == 3

    # Confirmation uses wait_template (re-evaluates live state and handles the
    # already-playing case), not wait_for_trigger (which only fires on a
    # transition and misses a group that never left "playing").
    assert "wait_for_trigger" not in block
    assert block.count("wait_template") == 3

    # Scope-safe: the decision is read from wait.completed at the top sequence
    # level, never from a variable reassigned inside a nested then-block.
    assert "not wait.completed" in block
    assert "wakeup_playback_confirmed" not in block

    # Everything — including the hard error stop — happens before the ramp.
    assert block.index("wait_template") < block.index("- repeat:")
    assert block.index("error: true") < block.index("- repeat:")


def test_play_wakeup_source_branches_url_vs_ma_uri() -> None:
    block = _script_block("music_assistant_play_wakeup_source")

    # Raw http(s) stream URL -> generic media_player stream (reliable on Sonos).
    assert "startswith('http')" in block
    assert "action: media_player.play_media" in block
    assert "media_content_type: music" in block
    # Music Assistant URI (spotify:/library:/tunein--) -> MA provider.
    assert "action: music_assistant.play_media" in block
    assert "enqueue: replace" in block


def test_prime_wake_group_sets_exact_member_volume_and_joins_to_bedroom() -> None:
    block = _script_block("music_assistant_prime_wake_group")

    assert 'action: media_player.volume_set' in block
    assert 'entity_id: "{{ group_members }}"' in block
    assert 'volume_level: "{{ starting_volume | float(0.01) }}"' in block
    assert 'action: media_player.join' in block
    assert 'entity_id: media_player.bedroom_sonos_2' in block
    assert "group_members | reject('eq', 'media_player.bedroom_sonos_2') | list" in block
    assert 'media_player.tiki_room_2' not in block


def test_spotify_wakeup_prepares_exact_guest_aware_wake_group() -> None:
    block = _script_block("spotify_wake_up")

    assert 'playback_entity_id:' in block
    assert 'regroup_after_play:' in block
    assert 'playback_player: media_player.bedroom_sonos_2' in block
    assert 'input_boolean.guest_mode' in block
    assert 'prepare_group_before_play:' not in block
    assert 'should_prepare_group_before_play' not in block
    assert 'should_regroup_after_play' not in block
    assert 'action: media_player.unjoin' not in block
    assert 'action: script.music_assistant_prepare_bedroom_group' not in block
    assert 'action: media_player.join' not in block
    assert 'action: script.music_assistant_prime_wake_group' in block
    assert 'starting_volume: 0.05' in block
    assert 'entity_id: "{{ playback_player }}"' in block
    assert 'entity_id: script.music_assistant_try_join_bedroom_group_after_play' not in block
    assert 'media_player.tiki_room_2' not in block


def test_bathroom_wakeup_automation_uses_policy_wake_group_members() -> None:
    block = _automation_block("play_music_in_bathroom_when_up")

    assert 'action: script.spotify_wake_up' in block
    assert block.count('playback_entity_id: media_player.ma_group_everywhere') == 2
    assert block.count('playback_entity_id: media_player.bedroom_sonos_2') == 0
    assert block.count('playback_entity_id: media_player.bathroom_sonos_2') == 0
    for entity_id in (
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
        "media_player.office_sonos_2",
        "media_player.den_sonos_2",
    ):
        assert entity_id in block
    assert "media_player.tiki_room_2" not in block
    assert 'regroup_after_play: true' not in block
    assert 'number.guest_room_fan_switch_ledintensitywhenoff' not in block
    assert 'media_player.media_stop' not in block


def test_stuck_morning_audio_scripts_are_recovered() -> None:
    block = _automation_block("recover_stuck_morning_audio_scripts")

    assert 'entity_id: script.music_assistant_prepare_bedroom_group' in block
    assert 'entity_id:\n          - script.spotify_wake_up\n          - script.music_assistant_radio_wake_up' in block
    assert 'minutes: 1' in block
    assert 'minutes: 12' in block
    assert 'action: script.turn_off' in block
    assert 'script.music_assistant_prepare_bedroom_group' in block
    assert 'script.music_assistant_radio_wake_up' in block
    assert 'script.spotify_wake_up' in block
    assert 'entity_id: input_boolean.morning_routine' in block


def test_bedtime_playlist_includes_explicit_somafm_station_urls() -> None:
    block = _script_block("spotify_bedtime")

    for station_url in (
        "https://ice1.somafm.com/groovesalad-128-mp3",
        "https://ice1.somafm.com/deepspaceone-128-mp3",
        "https://ice1.somafm.com/missioncontrol-128-mp3",
        "https://ice1.somafm.com/spacestation-128-mp3",
        "https://ice1.somafm.com/vaporwaves-128-mp3",
    ):
        assert f'"{station_url}"' in block

    for station_name in (
        "Groove Salad",
        "Deep Space One",
        "Mission Control",
        "Space Station Soma",
        "Vaporwaves",
    ):
        assert f'"{station_name}"' not in block

    assert "range(0, (plists | length))" in block
    assert "action: script.music_assistant_play_item" in block
    assert 'media_item: "{{ playlist }}"' in block
    assert 'media_type: "{{ bedtime_media_type }}"' in block
    assert "'somafm.com' in playlist" in block


def test_bedtime_verifies_primary_playback_and_falls_back_through_non_spotify_sources() -> None:
    block = _script_block("spotify_bedtime")

    for token in (
        "Play bedtime music on sync group",
        "bedtime_pre_playback_fingerprint",
        "Confirm primary bedtime playback changed the group media",
        "Confirm LoFi fallback changed the group media",
        "bedtime_apple_music_fallback_uri: \"apple_music://track/1492333325\"",
        "bedtime_local_library_fallback_uri: \"library://radio/17\"",
        "Apple Music bedtime fallback is",
        "Confirm Apple Music fallback changed the group media",
        "Local bedtime fallback is",
        "Confirm local library fallback changed the group media",
        "Bedtime audio failed",
        "state_attr(bedtime_playback_entity, 'media_content_id')",
        "state_attr(bedtime_playback_entity, 'media_title')",
        "!= bedtime_pre_playback_fingerprint",
        "seconds: 15",
        'value_template: "{{ not wait.completed }}"',
        "primary bedtime playback failed to start; playing LoFi fallback",
        "action: script.music_assistant_play_random_lofi_playlist",
        'entity_id: "{{ bedtime_playback_entity }}"',
        "playlist_name: Bedtime LoFi fallback",
        "log_name: Spotify Bedtime fallback is",
    ):
        assert token in block

    assert block.index("Play bedtime music on sync group") < block.index(
        "action: script.music_assistant_play_random_lofi_playlist"
    )
    assert block.index("action: script.music_assistant_play_random_lofi_playlist") < block.index(
        "entity_id: binary_sensor.owner_suite_bathroom_room_occupancy"
    )
    assert block.index("Confirm LoFi fallback changed the group media") < block.index(
        "Apple Music bedtime fallback is"
    )
    assert block.index("Confirm Apple Music fallback changed the group media") < block.index(
        "Local bedtime fallback is"
    )
    assert block.index("Confirm local library fallback changed the group media") < block.index(
        "entity_id: binary_sensor.owner_suite_bathroom_room_occupancy"
    )
    assert block.index("action: script.music_assistant_play_random_lofi_playlist") < block.index(
        "entity_id: script.spotify_bedtime_volume"
    )
    assert 'wait_template: "{{ is_state(bedtime_playback_entity, \'playing\') }}"' not in block


def test_music_assistant_dashboard_exposes_player_card() -> None:
    # The dashboard uses a dedicated Music Assistant tab with mass-player-card
    # instead of the old inline search panel.
    dashboard = DASHBOARD_PATH.read_text(encoding="utf-8")

    for token in (
        "Music Assistant",
        '"path": "music-assistant"',
        "custom:mass-player-card",
        "media_player.bedroom_sonos_2",
    ):
        assert token in dashboard


def test_music_assistant_search_helpers_are_restart_safe() -> None:
    package = MEDIA_PLAYER_PATH.read_text(encoding="utf-8")

    for token in (
        'music_assistant_search_query:',
        'initial: ""',
        'music_assistant_provider_filter:',
        '- All providers',
        'initial: All providers',
        'music_assistant_playlist_target:',
        'Bedtime || spotify_bedtime',
        'shell_command:',
        'music_assistant_append_playlist_item:',
    ):
        assert token in package


def test_bedroom_playlist_scripts_use_sequence_level_random_selection() -> None:
    # Playlist selection must be a sequence-level `variables:` action so that
    # `random` is evaluated fresh on every run rather than being cached when
    # the script definition is loaded.
    for script_id in (
        "bedroom_playlist_1",
        "bedroom_playlist_2",
        "bedroom_playlist_3",
        "bedroom_playlist_4",
    ):
        block = _script_block(script_id)
        # Script-level `variables:` must not contain playlist
        lines = block.splitlines()
        in_script_vars = False
        for line in lines:
            if line == "    variables:":
                in_script_vars = True
            elif in_script_vars and line.startswith("    ") and not line.startswith("      "):
                in_script_vars = False
            if in_script_vars and "playlist:" in line:
                raise AssertionError(
                    f"{script_id}: playlist found in script-level variables (must be sequence-level)"
                )
        # Sequence must begin with a variables action containing playlist
        assert "      - variables:" in block, f"{script_id}: missing sequence-level variables action"
        assert "          playlist: >-" in block, f"{script_id}: missing sequence-level playlist"
        assert (
            "action: script.music_assistant_play_bedroom_playlist_choice" in block
        ), f"{script_id}: missing shared bedroom playlist playback helper"
        assert "action: logbook.log" not in block, f"{script_id}: should delegate logging"
        assert (
            "action: script.music_assistant_play_spotify_uri" not in block
        ), f"{script_id}: should delegate Music Assistant playback"


def test_lofi_bedroom_playlist_scripts_delegate_to_shared_pool() -> None:
    primary_block = _script_block("bedroom_playlist_0")
    legacy_block = _script_block("bedroom_playlist_5")

    assert 'alias: "Play LoFi"' in primary_block
    assert "action: script.music_assistant_play_random_lofi_playlist" in primary_block
    assert "entity_id: media_player.bedroom_sonos_2" in primary_block
    assert "playlist_name: Lowfi" in primary_block
    assert "log_name: Cube Playlist is" in primary_block
    assert "playlist: >-" not in primary_block

    assert 'alias: "Play LoFi Legacy Delegate"' in legacy_block
    assert "action: script.bedroom_playlist_0" in legacy_block
    assert "playlist: >-" not in legacy_block


def test_bedtime_volume_rampdown_is_data_driven_without_repeating_delay_actions() -> None:
    block = _script_block("spotify_bedtime_volume")

    for token in (
        "bedtime_rampdown_steps:",
        "delay_minutes: 0",
        "delay_minutes: 2",
        "volume_level: 0.1",
        "volume_level: 0.07",
        "volume_level: 0.05",
        "volume_level: 0.01",
        "repeat:",
        'for_each: "{{ bedtime_rampdown_steps }}"',
        'minutes: "{{ repeat.item.delay_minutes }}"',
        'entity_id: "{{ repeat.item.entity_id }}"',
        'volume_level: "{{ repeat.item.volume_level }}"',
    ):
        assert token in block

    assert block.count("- delay:") == 1
    # Single data-driven volume_set that every step reuses.
    assert block.count("action: media_player.volume_set") == 1
    # Graceful degradation (#839): an unavailable member must never abort the
    # rampdown, so the volume_set tolerates errors and no step opts out.
    assert "continue_on_error: true" in block
    assert "continue_on_error: false" not in block


def test_spotify_bedtime_reapplies_repeat_to_started_queue_before_rampdown() -> None:
    block = _script_block("spotify_bedtime")

    tokens_in_order = (
        "action: script.music_assistant_play_item",
        "action: script.music_assistant_play_random_lofi_playlist",
        "Ensure bedtime queue repeats after playback starts",
        "action: media_player.repeat_set",
        "entity_id: binary_sensor.owner_suite_bathroom_room_occupancy",
        "entity_id: script.spotify_bedtime_volume",
    )

    cursor = -1
    for token in tokens_in_order:
        next_cursor = block.index(token, cursor + 1)
        assert next_cursor > cursor, token
        cursor = next_cursor

    assert block.count("action: media_player.repeat_set") == 2
    assert block.count("repeat: all") == 2

    repeat_after_start = block.split("Ensure bedtime queue repeats after playback starts", 1)[1]
    for token in (
        "continue_on_error: true",
        "repeat: all",
        'entity_id: "{{ bedtime_playback_entity }}"',
    ):
        assert token in repeat_after_start


def test_arrival_and_wakeup_scripts_use_sequence_level_playlist_selection() -> None:
    # Same caching concern as bedroom_playlist scripts.
    for script_id in ("spotify_arrival", "spotify_wake_up"):
        block = _script_block(script_id)
        assert "      - variables:" in block, f"{script_id}: missing sequence-level variables action"
        assert "          playlist: >-" in block, f"{script_id}: missing sequence-level playlist"
        # The top-level variables block (for state-dependent fields) must NOT contain playlist
        lines = block.splitlines()
        in_script_vars = False
        for line in lines:
            if line == "    variables:":
                in_script_vars = True
            elif in_script_vars and line.startswith("    ") and not line.startswith("      "):
                in_script_vars = False
            if in_script_vars and line.strip().startswith("playlist:"):
                raise AssertionError(
                    f"{script_id}: playlist found in script-level variables (must be sequence-level)"
                )


def test_arrival_verifies_retries_and_only_logs_success_after_playback() -> None:
    block = _script_block("spotify_arrival")

    for token in (
        "arrival_pre_playback_fingerprint",
        "Confirm arrival playback changed the group media",
        "Confirm arrival playback after the retry",
        "state_attr(playback_entity, 'media_content_id')",
        "!= arrival_pre_playback_fingerprint",
        "seconds: 15",
        'value_template: "{{ not wait.completed }}"',
        'value_template: "{{ wait.completed }}"',
        "Arrival music retry",
        "arrival_audio_failed",
        "Arrival audio failed",
    ):
        assert token in block, token

    assert block.count("action: script.music_assistant_play_spotify_uri") == 2
    assert block.index("Confirm arrival playback changed the group media") < block.index(
        "Arrival music retry"
    )
    assert block.index("Confirm arrival playback after the retry") < block.index(
        "name: Arrival music is"
    )


def test_arrival_wait_steps_stay_at_top_sequence_level() -> None:
    # HA copies variables into nested then/choose sub-scripts, so a `wait` set
    # inside `then:` is not visible to a later top-level step. If the retry
    # confirmation were nested, the final `{{ wait.completed }}` check would read
    # the first (timed-out) wait and report failure even when the retry worked.
    block = _script_block("spotify_arrival")
    top_level_step = "      - "

    for line in block.splitlines():
        if "wait_template:" in line:
            assert line.startswith("        wait_template:"), (
                f"arrival wait_template is nested below the top sequence level: {line!r}"
            )

    retry_confirm = "      - alias: \"Confirm arrival playback after the retry\""
    assert retry_confirm in block.splitlines(), (
        "retry confirmation must be a top-level sequence step"
    )

    # The retry `then:` block may only issue actions, never confirm.
    retry_start = block.index('alias: "Retry arrival music once when the primary request did not start"')
    retry_end = block.index(retry_confirm.strip(), retry_start)
    assert "wait_template" not in block[retry_start:retry_end], (
        "retry then: block must not contain the confirmation wait"
    )
    assert top_level_step in block


def test_arrival_fingerprint_is_captured_after_the_arrival_delay() -> None:
    # An already-playing group advances tracks on its own during the 90s arrival
    # delay, so a fingerprint taken before it would differ by playback time alone
    # and let a failed play request read as success.
    block = _script_block("spotify_arrival")

    delay_index = block.index("seconds: 90")
    fingerprint_index = block.index("arrival_pre_playback_fingerprint: >-")
    play_index = block.index('alias: "Play arrival music via Music Assistant"')
    volume_index = block.index("volume_level: 0.30")

    assert delay_index < fingerprint_index, (
        "fingerprint must be captured after the 90s arrival delay"
    )
    assert volume_index < fingerprint_index, (
        "fingerprint must be captured after shuffle/volume setup"
    )
    assert fingerprint_index < play_index, (
        "fingerprint must be captured before the play request"
    )
