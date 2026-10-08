from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIVING_ROOM_TILE = ROOT / "lovelace" / "tiles" / "tiles_living_room.yaml"
OWNER_SUITE_TILE = ROOT / "lovelace" / "tiles" / "tiles_master_bedroom.yaml"
OFFICE_TILE = ROOT / "lovelace" / "tiles" / "tiles_office.yaml"
BATHROOM_TILE = ROOT / "lovelace" / "tiles" / "tiles_bathroom.yaml"
CONFIGURATION = ROOT / "configuration.yaml"


def _card_block(text: str, entity_id: str) -> str:
    marker = f"    entity: {entity_id}\n"
    entity_position = text.index(marker)
    card_start = text.rfind("  - type:", 0, entity_position)
    card_end = text.find("\n  - type:", entity_position)
    if card_start == -1:
        raise AssertionError(f"Could not find card start for {entity_id}")
    return text[card_start : card_end if card_end != -1 else len(text)]


def test_basement_media_cards_use_native_tiles() -> None:
    text = LIVING_ROOM_TILE.read_text(encoding="utf-8")

    assert "custom:mini-media-player" not in text

    apple_tv = _card_block(text, "media_player.basement")
    assert apple_tv.startswith("  - type: tile\n")
    assert "features_position: bottom" in apple_tv
    assert (
        "controls:\n"
        "          - turn_on\n"
        "          - media_play_pause\n"
        "          - media_stop\n"
        "          - turn_off"
    ) in apple_tv
    assert "media-player-volume" not in apple_tv

    television = _card_block(text, "media_player.lg_webos_smart_tv")
    assert television.startswith("  - type: tile\n")
    assert (
        "controls:\n"
        "          - media_play_pause\n"
        "          - media_stop\n"
        "          - turn_off"
    ) in television
    assert "type: media-player-volume-buttons" in television
    assert "step: 5" in television
    assert "show_mute_button: true" in television


def test_native_tiles_preserve_previous_source_and_sound_mode_scope() -> None:
    text = LIVING_ROOM_TILE.read_text(encoding="utf-8")

    assert "media-player-source" not in text
    assert "media-player-sound-mode" not in text


def test_mini_media_player_stays_loaded_for_sonos_group_controls() -> None:
    configuration = CONFIGURATION.read_text(encoding="utf-8")
    grouped_tiles = [OWNER_SUITE_TILE, OFFICE_TILE, BATHROOM_TILE]

    assert "/hacsfiles/mini-media-player/mini-media-player-bundle.js" in configuration
    for tile_path in grouped_tiles:
        tile = tile_path.read_text(encoding="utf-8")
        assert "type: custom:mini-media-player" in tile
        assert "speaker_group:" in tile
