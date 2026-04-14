from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIGHT_PATH = ROOT / "packages" / "light.yaml"


def _automation_block(automation_id: str) -> str:
    text = LIGHT_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - (?:id|alias): |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in packages/light.yaml")
    return match.group(0)


def test_basement_lights_auto_on_retries_after_media_shutdown_handoffs() -> None:
    block = _automation_block("basement_lights_auto_on")

    for token in (
        'entity_id: binary_sensor.basement_landing_occupancy',
        'entity_id: media_player.basement\n        from: "playing"',
        'entity_id: media_player.basement\n        from: "paused"',
        'entity_id: media_player.plex_basement_apple_tv\n        from: "playing"',
        'entity_id: media_player.plex_basement_apple_tv\n        from: "paused"',
        "seconds: 3",
    ):
        assert token in block


def test_basement_lights_auto_on_requires_occupancy_and_non_playback_states() -> None:
    block = _automation_block("basement_lights_auto_on")

    for token in (
        'alias: "Basement landing still occupied"',
        'entity_id: binary_sensor.basement_landing_occupancy\n        state: "on"',
        'entity_id: media_player.basement\n                state: "playing"',
        'entity_id: media_player.basement\n                state: "paused"',
        'entity_id: media_player.plex_basement_apple_tv\n                state: "playing"',
        'entity_id: media_player.plex_basement_apple_tv\n                state: "paused"',
        "light.basement_great_room",
    ):
        assert token in block
