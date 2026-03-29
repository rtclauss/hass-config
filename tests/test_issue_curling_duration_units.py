from __future__ import annotations

from pathlib import Path


CURLING_PATH = Path(__file__).resolve().parents[1] / "packages" / "curling.yaml"


def test_curling_duration_sensors_use_valid_units_and_numeric_startup_fallbacks() -> None:
    text = CURLING_PATH.read_text(encoding="utf-8")

    assert 'unit_of_measurement: "min"' in text
    assert 'unit_of_measurement: "minutes"' not in text
    assert '{{now()}}' not in text
    assert "\n            0\n" in text
