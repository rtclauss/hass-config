from __future__ import annotations

import re
from pathlib import Path


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def _automation_block(automation_id: str) -> str:
    lines = CAR_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"  - alias: {automation_id}", f"    id: {automation_id}"):
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_tire_rotations_trigger_template_handles_missing_odometer_values() -> None:
    block = _automation_block("Tire Rotations")

    assert "trigger: numeric_state" in block
    assert "entity_id: sensor.nigori_odometer" in block
    assert "state | int" not in block
    assert "has_value('sensor.nigori_odometer')" in block
    assert "states('sensor.nigori_odometer') | float(default=0)" in block
    assert re.search(r"below:\s+20", block)
