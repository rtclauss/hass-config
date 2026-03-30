from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATER_SOFTENER_PATH = ROOT / "packages" / "water_softener.yaml"


def _automation_block(path: Path, automation_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")
    return match.group(0)


def test_salt_purchased_ignores_empty_or_invalid_reply_text() -> None:
    block = _automation_block(WATER_SOFTENER_PATH, "salt_purchased")

    assert 'trigger.event.data.reply_text | int' not in block
    assert 'trigger.event.data.reply_text | default("", true) | trim' in block
    assert "purchased_text | regex_match('^\\d+$')" in block
    assert 'states("input_number.bags_of_salt_at_home") | int(default=0)' in block
    assert 'current_bags + (purchased_text | int(default=0))' in block
