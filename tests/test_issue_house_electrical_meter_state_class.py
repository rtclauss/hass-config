from __future__ import annotations

from pathlib import Path


UTILITIES_PATH = Path(__file__).resolve().parents[1] / "packages" / "utilities.yaml"


def test_house_electrical_meter_uses_energy_compatible_state_class() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    block = text.split("name: house_electrical_meter", 1)[1].split(
        "name: house_electrical_meter_non_ev", 1
    )[0]
    assert "device_class: energy" in block
    assert "state_class: total_increasing" in block
    assert "state_class: measurement" not in block
