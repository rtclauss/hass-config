from __future__ import annotations

from pathlib import Path


FANS_PATH = Path(__file__).resolve().parents[1] / "packages" / "fans.yaml"


def _automation_block(alias: str) -> str:
    lines = FANS_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  - alias: {alias}"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find automation alias {alias!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - alias: "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_den_ceiling_bond_reconcile_uses_expected_sensors_and_bond_service() -> None:
    block = _automation_block("den_ceiling_bond_state_reconcile")

    assert "binary_sensor.den_motion_occupancy" in block
    assert "sensor.den_motion_illuminance" in block
    assert "light.den_ceiling" in block
    assert "action: bond.set_light_power_tracked_state" in block
    assert "above: 100" in block
    assert "below: 10" in block


def test_den_ceiling_bond_reconcile_excludes_neighboring_spill_lights() -> None:
    block = _automation_block("den_ceiling_bond_state_reconcile")

    assert "light.den_flood_switch" in block
    assert "light.den_lamp" in block
    assert "light.kitchen_all" in block
    assert "light.tiki_room_lights_tiki_room_strip" in block


def test_den_ceiling_bond_reconcile_has_overnight_force_off_failsafe() -> None:
    block = _automation_block("den_ceiling_bond_state_reconcile")

    assert 'after: "00:30:00"' in block
    assert "before: sunrise" in block
    assert 'state: "off"' in block
    assert "hours: 1" in block
    assert "action: light.turn_off" in block
    assert 'minutes: "/30"' in block
