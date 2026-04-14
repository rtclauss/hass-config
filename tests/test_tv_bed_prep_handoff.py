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


def test_tv_bed_prep_handles_lg_off_to_unavailable_handoff() -> None:
    block = _automation_block("tv_off_at_night_bed_prep")

    assert block.count("entity_id: media_player.lg_webos_smart_tv") == 3
    assert 'from: "on"\n        to: "off"' in block
    assert 'from: "on"\n        to: "unavailable"' in block
    assert 'from: "off"\n        to: "unavailable"' in block
    assert "seconds: 15" in block
    assert "seconds: 5" in block
