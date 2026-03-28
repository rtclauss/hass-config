from __future__ import annotations

import re
from pathlib import Path


MEDIA_PLAYER_PATH = Path(__file__).resolve().parents[1] / "packages" / "media_player.yaml"


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


def test_music_assistant_item_helper_handles_spotify_and_radio_items() -> None:
    block = _script_block("music_assistant_play_item")

    assert "Spotify URI, open.spotify.com URL, or Music Assistant radio item name" in block
    assert "raw_item.startswith('spotify:')" in block
    assert "raw_item.startswith('https://open.spotify.com/')" in block
    assert "spotify--Tviw9k66://" in block
    assert "          radio" in block


def test_spotify_wrapper_delegates_to_generic_music_assistant_helper() -> None:
    block = _script_block("music_assistant_play_spotify_uri")

    assert "action: script.music_assistant_play_item" in block
    assert 'media_item: "{{ spotify_uri }}"' in block


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

    assert "action: script.music_assistant_play_item" in block
    assert 'media_item: "{{ playlist }}"' in block
