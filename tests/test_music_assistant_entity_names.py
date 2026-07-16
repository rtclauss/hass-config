from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MUSIC_ASSISTANT_PLAYERS = {
    "media_player.ma_bedroom": "Bedroom",
    "media_player.ma_bathroom": "Bathroom",
    "media_player.ma_office": "Office",
    "media_player.ma_den": "Den",
    "media_player.ma_tiki_room": "Tiki Room",
}

LEGACY_ROOM_PLAYERS = {
    "media_player.bedroom_sonos",
    "media_player.bedroom_sonos_2",
    "media_player.bathroom_sonos",
    "media_player.bathroom_sonos_2",
    "media_player.office_sonos",
    "media_player.office_sonos_2",
    "media_player.den_sonos",
    "media_player.den_sonos_2",
    "media_player.tiki_room_2",
    "media_player.tiki_room_3",
}

OPERATIONAL_PATHS = (
    ROOT / "packages",
    ROOT / "lovelace",
    ROOT / ".storage" / "lovelace.dashboard_strategy",
    ROOT / ".storage" / "lovelace.ryan_new_mushroom",
)


def _operational_files() -> list[Path]:
    files: list[Path] = []
    for path in OPERATIONAL_PATHS:
        if path.is_dir():
            files.extend(path.rglob("*.yaml"))
        else:
            files.append(path)
    return files


def test_operational_config_uses_explicit_music_assistant_room_entity_ids() -> None:
    violations: list[str] = []

    for path in _operational_files():
        text = path.read_text(encoding="utf-8")
        for legacy_entity_id in LEGACY_ROOM_PLAYERS:
            if legacy_entity_id in text:
                violations.append(f"{path.relative_to(ROOT)}: {legacy_entity_id}")

    assert violations == []


def test_music_assistant_docs_define_siri_friendly_registry_names() -> None:
    docs = (ROOT / "docs" / "music_assistant.md").read_text(encoding="utf-8")

    for entity_id, registry_name in MUSIC_ASSISTANT_PLAYERS.items():
        assert f"`{entity_id}` | `{registry_name}`" in docs


def test_agent_guidance_uses_explicit_music_assistant_room_entity_ids() -> None:
    guidance = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Always target the explicit MA room entities" in guidance
    for entity_id in MUSIC_ASSISTANT_PLAYERS:
        assert f"`{entity_id}`" in guidance
    assert "Always target the MA `*_sonos_2` entities" not in guidance
