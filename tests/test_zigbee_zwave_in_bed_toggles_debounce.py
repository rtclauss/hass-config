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


def test_in_bed_toggles_requires_sustained_vacancy_before_reentry() -> None:
    block = _automation_block("in_bed_toggles")

    bed_occupied_trigger, remainder = block.split("id: bed-occupied", maxsplit=1)
    bed_unoccupied_trigger = remainder.split("id: bed-unoccupied", maxsplit=1)[0]
    assert 'to: "on"' in bed_occupied_trigger
    assert "for:" not in bed_occupied_trigger
    assert 'to: "off"' in bed_unoccupied_trigger
    assert "for:" in bed_unoccupied_trigger
    assert "seconds: 5" in bed_unoccupied_trigger

    occupied_branch = remainder.split("id: bed-unoccupied", maxsplit=1)[1].split("sequence:", maxsplit=1)[0]
    assert "condition: state" in occupied_branch
    assert "entity_id: input_boolean.master_bed_occupancy" in occupied_branch
    assert 'state: "off"' in occupied_branch

    assert "action: cover.close_cover" in block
    assert "cover.owner_suite_blinds_ha" in block
    assert "cover.garage_door" in block


def test_in_bed_toggles_has_no_dangling_commented_debounce_condition() -> None:
    block = _automation_block("in_bed_toggles")

    assert "# condition:" not in block
    assert "#     seconds: 5" not in block


def _package_text() -> str:
    return ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")


def test_combined_bed_pressure_sums_both_pads() -> None:
    text = _package_text()
    block = text.split("name: bed_presence_combined_pressure", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]

    assert "- platform: min_max\n    name: bed_presence_combined_pressure" in text
    assert "type: sum" in block
    assert "sensor.bed_presence_2d0670_left_pressure" in block
    assert "sensor.bed_presence_2d0670_right_pressure" in block


def test_combined_bed_occupancy_threshold_has_hysteresis() -> None:
    block = _package_text().split("name: bed_presence_combined_occupied", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]

    assert "entity_id: sensor.bed_presence_combined_pressure" in block
    assert "upper: 25" in block
    assert "hysteresis: 10" in block


def test_bayesian_bed_occupancy_uses_combined_pressure() -> None:
    block = _package_text().split('name: "Bayesian Bed Occupancy"', maxsplit=1)[1].split("\n\n  # - platform", maxsplit=1)[0]

    assert "entity_id: binary_sensor.bed_presence_combined_occupied" in block
    assert "entity_id: binary_sensor.bed_presence_2d0670_bed_occupied_either" not in block


def test_in_bed_toggles_waits_for_fusion_before_vacating() -> None:
    block = _automation_block("in_bed_toggles")
    unoccupied_branch = block.split("id: bed-unoccupied", maxsplit=2)[2]

    gate = unoccupied_branch.split("action: input_boolean.turn_off", maxsplit=1)[0]
    assert "entity_id: binary_sensor.bayesian_bed_occupancy" in gate
    assert 'state: "off"' in gate
