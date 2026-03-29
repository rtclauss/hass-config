from __future__ import annotations

import re
from pathlib import Path


LIGHT_PATH = Path(__file__).resolve().parents[1] / "packages" / "light.yaml"
ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _script_block(script_id: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def test_reset_script_keeps_den_flood_switch_group_membership() -> None:
    block = _script_block("reset_inovelli_switches")

    assert 'group: "Den/Floods"' in block
    assert 'device: "Den/Flood Switch"' in block
    assert "endpoint: 2" in block


def test_reset_script_keeps_den_flood_switch_bindings_to_group_and_lamp() -> None:
    block = _script_block("reset_inovelli_switches")

    assert 'from: "Den/Flood Switch"' in block
    assert 'to: "Den/Floods"' in block
    assert 'to: "Den/Lamp"' in block
    assert "genScenes" in block


def test_light_package_uses_den_flood_switch_entity_name() -> None:
    text = LIGHT_PATH.read_text(encoding="utf-8")

    assert "light.den_flood_switch" in text
    assert "light.den_wall_switch" not in text
