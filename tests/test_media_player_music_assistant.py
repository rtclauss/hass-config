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
        "input_text.music_assistant_provider_filter",
        "input_select.music_assistant_search_media_type",
        "input_select.music_assistant_search_results",
        "music_assistant.search",
        "Direct URI ||",
        "provider_blob",
        "No results found",
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


def test_bedtime_playlist_includes_somafm_station_names() -> None:
    block = _script_block("spotify_bedtime")

    for station in (
        "Groove Salad",
        "Deep Space One",
        "Mission Control",
        "Space Station Soma",
        "Vaporwaves",
    ):
        assert f'"{station}"' in block

    assert "range(0, (plists | length))" in block
    assert "action: script.music_assistant_play_item" in block
    assert 'media_item: "{{ playlist }}"' in block


def test_music_assistant_dashboard_exposes_search_controls() -> None:
    dashboard = DASHBOARD_PATH.read_text(encoding="utf-8")

    for token in (
        "Music Assistant",
        "input_text.music_assistant_search_query",
        "input_text.music_assistant_provider_filter",
        "input_select.music_assistant_search_media_type",
        "input_select.music_assistant_search_results",
        "script.music_assistant_search_music",
        "script.music_assistant_play_selected_search_result",
    ):
        assert token in dashboard
