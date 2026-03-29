from __future__ import annotations

import re
from pathlib import Path


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def test_tire_rotations_trigger_template_handles_missing_odometer_values() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "alias: Tire Rotations" in text
    assert "id: tire_rotation" in text
    assert "trigger: numeric_state" in text
    assert "entity_id: sensor.nigori_odometer" in text
    assert "state | int" not in text
    assert "has_value('sensor.nigori_odometer')" in text
    assert "states('sensor.nigori_odometer') | float(default=0)" in text
    assert re.search(r"below:\s+20", text)
