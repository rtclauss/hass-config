from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TV_PATH = ROOT / "packages" / "tv.yaml"


def _automation_block(automation_id: str) -> str:
    text = TV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in packages/tv.yaml")
    return match.group(0)


def test_tv_bed_prep_handles_lg_shutdown_handoff_without_unconditional_offline_fire() -> None:
    block = _automation_block("tv_off_at_night_bed_prep")

    assert 'id: lg-tv-off' in block
    assert 'id: lg-tv-unavailable' in block
    assert 'id: basement-player-off' in block
    assert 'from: "on"\n        to: "off"' in block
    assert 'from: "on"\n        to: "unavailable"' in block
    assert 'entity_id: media_player.basement\n        to: "off"' in block
    assert "seconds: 15" in block
    assert "seconds: 5" in block
    assert "trigger.id != 'basement-player-off'" in block
    assert "media_player.plex_basement_apple_tv" in block
