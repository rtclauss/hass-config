from __future__ import annotations

import re
from pathlib import Path


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def _automation_block(automation_id: str) -> str:
    text = CAR_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_tesla_departure_planner_uses_state_check_for_home_presence() -> None:
    block = _automation_block("tesla_departure_planner_apply")

    assert 'entity_id: device_tracker.nigori_location_tracker' in block
    assert 'condition: zone' not in block
    assert 'state: "home"' in block
    assert 'zone: zone.home' not in block
