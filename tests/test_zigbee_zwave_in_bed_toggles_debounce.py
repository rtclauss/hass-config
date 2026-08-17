from __future__ import annotations

from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _automation_block(automation_id: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
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


def test_in_bed_toggles_requires_bed_occupancy_to_hold_before_closing_blinds() -> None:
    block = _automation_block("in_bed_toggles")

    bed_occupied_trigger = block.split('id: bed-occupied', maxsplit=1)[0]
    assert 'to: "on"' in bed_occupied_trigger
    assert "for:" in bed_occupied_trigger
    assert "seconds: 5" in bed_occupied_trigger

    assert "action: cover.close_cover" in block
    assert "cover.owner_suite_blinds_ha" in block
    assert "cover.garage_door" in block


def test_in_bed_toggles_has_no_dangling_commented_debounce_condition() -> None:
    block = _automation_block("in_bed_toggles")

    assert "# condition:" not in block
    assert "#     seconds: 5" not in block
