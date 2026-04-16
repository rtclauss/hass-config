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


def test_music_assistant_item_helper_is_generic_pass_through() -> None:
    block = _script_block("music_assistant_play_item")

    assert "Music Assistant URI, open.spotify.com URL, or plain item name" in block
    assert "raw_media_type" in block
    assert "music_assistant.play_media" in block
    assert "spotify--Tviw9k66://" not in block
    assert "raw_item.startswith('spotify:')" not in block
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


def test_house_party_helper_joins_every_sonos_zone() -> None:
    block = _script_block("music_assistant_prepare_house_party_group")

    assert "Join the whole Sonos house group" in block
    for media_player in (
        "media_player.den_sonos_2",
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
        "media_player.office_sonos_2",
        "media_player.tiki_room_2",
    ):
        assert media_player in block


def test_bedroom_group_helper_restarts_instead_of_blocking_new_runs() -> None:
    block = _script_block("music_assistant_prepare_bedroom_group")

    assert 'mode: restart' in block
    assert 'action: media_player.unjoin' in block
    for media_player in (
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
        "media_player.den_sonos_2",
        "media_player.office_sonos_2",
    ):
        assert media_player in block


def test_arrival_group_helper_resets_players_before_regrouping() -> None:
    block = _script_block("music_assistant_prepare_arrival_group")

    assert 'action: media_player.unjoin' in block
    assert '"Join whole-house arrival group"' in block
    for media_player in (
        "media_player.bedroom_sonos_2",
        "media_player.bathroom_sonos_2",
        "media_player.den_sonos_2",
        "media_player.office_sonos_2",
        "media_player.tiki_room_2",
    ):
        assert media_player in block


def test_arrival_music_does_not_retry_regroup_after_playback_starts() -> None:
    arrival_block = _script_block("spotify_arrival")

    assert 'action: script.music_assistant_prepare_arrival_group' in arrival_block
    assert 'action: script.music_assistant_play_spotify_uri' in arrival_block
    assert 'entity_id: script.music_assistant_try_join_arrival_group_after_play' not in arrival_block


def test_bedtime_join_retry_runs_after_playback_starts() -> None:
    helper_block = _script_block("music_assistant_try_join_bedroom_group_after_play")
    bedtime_block = _script_block("spotify_bedtime")

    assert 'mode: restart' in helper_block
    assert 'seconds: 2' in helper_block
    assert 'action: script.turn_on' in helper_block
    assert 'entity_id: script.music_assistant_prepare_bedroom_group' in helper_block
    assert 'entity_id: script.music_assistant_try_join_bedroom_group_after_play' in bedtime_block
    assert bedtime_block.index('action: script.music_assistant_play_item') < bedtime_block.index(
        'entity_id: script.music_assistant_try_join_bedroom_group_after_play'
    )


def test_radio_wakeup_prepares_group_before_play_and_only_retries_regroup_when_requested() -> None:
    block = _script_block("music_assistant_radio_wake_up")

    assert 'playback_entity_id:' in block
    assert 'prepare_group_before_play:' in block
    assert 'regroup_after_play:' in block
    assert 'playback_player' in block
    assert 'should_prepare_group_before_play' in block
    assert 'should_regroup_after_play' in block
    assert 'action: media_player.unjoin' in block
    assert 'action: script.music_assistant_prepare_bedroom_group' in block
    assert "{{ prepare_group_before_play | default(playback_player == 'media_player.bedroom_sonos_2') | bool }}" in block
    assert "{{ regroup_after_play | default(false) | bool }}" in block
    assert 'entity_id: "{{ playback_player }}"' in block
    assert 'entity_id: script.music_assistant_try_join_bedroom_group_after_play' in block
    assert block.index('action: music_assistant.play_media') < block.index(
        'entity_id: script.music_assistant_try_join_bedroom_group_after_play'
    )


def test_spotify_wakeup_prepares_group_before_play_and_only_retries_regroup_when_requested() -> None:
    block = _script_block("spotify_wake_up")

    assert 'playback_entity_id:' in block
    assert 'prepare_group_before_play:' in block
    assert 'regroup_after_play:' in block
    assert 'playback_player' in block
    assert 'should_prepare_group_before_play' in block
    assert 'should_regroup_after_play' in block
    assert 'action: media_player.unjoin' in block
    assert 'action: script.music_assistant_prepare_bedroom_group' in block
    assert "{{ prepare_group_before_play | default(playback_player == 'media_player.bedroom_sonos_2') | bool }}" in block
    assert "{{ regroup_after_play | default(false) | bool }}" in block
    assert 'entity_id: "{{ playback_player }}"' in block
    assert 'entity_id: script.music_assistant_try_join_bedroom_group_after_play' in block
    assert block.index('action: script.music_assistant_play_spotify_uri') < block.index(
        'entity_id: script.music_assistant_try_join_bedroom_group_after_play'
    )


def test_bathroom_wakeup_automation_targets_bedroom_coordinator() -> None:
    block = _automation_block("play_music_in_bathroom_when_up")

    assert 'action: script.spotify_wake_up' in block
    # Must play on the group coordinator (bedroom), not a group member (bathroom),
    # to avoid the race condition where the playback queue is lost when
    # music_assistant_prepare_bedroom_group reforms the group.
    assert block.count('playback_entity_id: media_player.bedroom_sonos_2') == 2
    assert block.count('playback_entity_id: media_player.bathroom_sonos_2') == 0
    assert block.count('regroup_after_play: true') == 2
    assert 'media_player.media_stop' not in block


def test_stuck_morning_audio_scripts_are_recovered() -> None:
    block = _automation_block("recover_stuck_morning_audio_scripts")

    assert 'entity_id: script.music_assistant_prepare_bedroom_group' in block
    assert 'entity_id:\n          - script.spotify_wake_up\n          - script.music_assistant_radio_wake_up' in block
    assert 'minutes: 1' in block
    assert 'minutes: 3' in block
    assert 'action: script.turn_off' in block
    assert 'script.music_assistant_prepare_bedroom_group' in block
    assert 'script.music_assistant_radio_wake_up' in block
    assert 'script.spotify_wake_up' in block
    assert 'entity_id: input_boolean.morning_routine' in block


def test_bedtime_playlist_includes_explicit_somafm_station_urls() -> None:
    block = _script_block("spotify_bedtime")

    for station_url in (
        "https://somafm.com/groovesalad.pls",
        "https://somafm.com/deepspaceone.pls",
        "https://somafm.com/missioncontrol.pls",
        "https://somafm.com/spacestation.pls",
        "https://somafm.com/vaporwaves.pls",
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
    assert "playlist.startswith('https://somafm.com/')" in block


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
        "bedroom_playlist_0",
        "bedroom_playlist_1",
        "bedroom_playlist_2",
        "bedroom_playlist_3",
        "bedroom_playlist_4",
        "bedroom_playlist_5",
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
