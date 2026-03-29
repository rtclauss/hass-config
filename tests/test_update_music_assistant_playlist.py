from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "update_music_assistant_playlist.py"
SPEC = importlib.util.spec_from_file_location("update_music_assistant_playlist", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SUPPORTED_PLAYLIST_SCRIPTS = MODULE.SUPPORTED_PLAYLIST_SCRIPTS
append_item_to_playlist_config = MODULE.append_item_to_playlist_config


def _script_block(text: str, script_id: str) -> str:
    lines = text.splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and lines[index].endswith(":") and not lines[index].startswith("    "):
            return "\n".join(lines[start:index])

    return "\n".join(lines[start:])


def test_append_item_to_playlist_config_appends_once(media_player_config_text: str) -> None:
    updated, changed = append_item_to_playlist_config(
        media_player_config_text,
        "spotify_bedtime",
        "spotify:playlist:test-addition",
    )

    assert changed is True
    block = _script_block(updated, "spotify_bedtime")
    assert '"spotify:playlist:test-addition"' in block
    assert block.count('"spotify:playlist:test-addition"') == 1


def test_append_item_to_playlist_config_deduplicates(media_player_config_text: str) -> None:
    updated, changed = append_item_to_playlist_config(
        media_player_config_text,
        "spotify_bedtime",
        "Groove Salad",
    )

    assert changed is False
    assert updated == media_player_config_text


def test_append_item_to_playlist_config_rejects_unknown_targets(media_player_config_text: str) -> None:
    with pytest.raises(ValueError, match="Unsupported playlist target"):
        append_item_to_playlist_config(
            media_player_config_text,
            "music_assistant_search_music",
            "spotify:playlist:test-addition",
        )


def test_supported_playlist_scripts_cover_dashboard_targets() -> None:
    assert SUPPORTED_PLAYLIST_SCRIPTS == {
        "bedroom_playlist_0",
        "bedroom_playlist_1",
        "bedroom_playlist_2",
        "bedroom_playlist_3",
        "bedroom_playlist_4",
        "bedroom_playlist_5",
        "spotify_arrival",
        "spotify_bedtime",
        "spotify_wake_up",
    }
