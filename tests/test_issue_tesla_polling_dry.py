from __future__ import annotations

import re
from pathlib import Path


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def _automation_block(automation_id: str) -> str:
    text = CAR_PATH.read_text(encoding="utf-8")
    automation_starts = [
        match.start() for match in re.finditer(r"^  - (?:id|alias): ", text, re.MULTILINE)
    ]

    for index, start in enumerate(automation_starts):
        end = (
            automation_starts[index + 1]
            if index + 1 < len(automation_starts)
            else len(text)
        )
        block = text[start:end]
        if re.search(rf"^    id: {re.escape(automation_id)}$", block, re.MULTILINE):
            return block
        if re.search(rf"^  - id: {re.escape(automation_id)}$", block, re.MULTILINE):
            return block

    raise AssertionError(f"Could not find automation block {automation_id!r}")


def test_tesla_polling_legacy_duplicate_automation_ids_are_removed() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "tesla_short_polling_charger_connected" not in text
    assert "tesla_short_polling_driving" not in text
    assert "tesla_long_polling_charger_disconnected" not in text
    assert "tesla_long_polling_charger_diconnected_parked" not in text


def test_tesla_short_polling_startup_uses_one_native_or_condition() -> None:
    block = _automation_block("tesla_short_polling_startup")

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert "condition: or" in block
    assert "entity_id: binary_sensor.nigori_charging" in block
    assert 'state: "on"' in block
    assert "entity_id: binary_sensor.nigori_parking_brake" in block
    assert 'state: "off"' in block
    assert 'delay: "00:01:00"' in block
    assert "action: tesla_custom.polling_interval" in block
    assert "scan_interval: 30" in block


def test_tesla_long_polling_waits_for_idle_and_unplugged_state() -> None:
    block = _automation_block("tesla_long_polling_idle_unplugged")

    assert "mode: restart" in block
    assert block.count("trigger: state") == 2
    assert "id: charger_disconnected" in block
    assert "id: parked" in block
    assert "entity_id: binary_sensor.nigori_charging" in block
    assert "entity_id: binary_sensor.nigori_parking_brake" in block
    assert block.count("minutes: 15") == 2
    assert 'state: "off"' in block
    assert 'state: "on"' in block
    assert "action: tesla_custom.polling_interval" in block
    assert "scan_interval: 660" in block
