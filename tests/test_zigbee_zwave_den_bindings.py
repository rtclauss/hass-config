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


def _device_binding_topic(block: str, payload_fragment: str) -> str:
    lines = block.splitlines()
    payload_index = next(
        index for index, line in enumerate(lines) if payload_fragment in line
    )
    topic_index = max(
        index
        for index in range(payload_index)
        if "topic: zigbee2mqtt/bridge/request/device/" in lines[index]
    )
    return lines[topic_index].strip()


def test_reset_script_keeps_den_flood_switch_whole_room_binding() -> None:
    block = _script_block("reset_inovelli_switches")
    payload = '"from":"Den/Flood Switch/2","to":"Den/All"}'

    assert block.count(payload) == 1
    assert _device_binding_topic(block, payload) == (
        "topic: zigbee2mqtt/bridge/request/device/bind"
    )
    assert "Den/Wall Switch" not in block


def test_reset_script_keeps_den_flood_switch_group_binding() -> None:
    block = _script_block("reset_inovelli_switches")
    payload = '"from":"Den/Flood Switch/2","to":"Den/Floods"}'

    assert block.count(payload) == 1
    assert _device_binding_topic(block, payload) == (
        "topic: zigbee2mqtt/bridge/request/device/bind"
    )
    assert '"group":"Den/Floods"' in block


def test_light_package_uses_den_flood_switch_entity_name() -> None:
    text = LIGHT_PATH.read_text(encoding="utf-8")

    assert "light.den_flood_switch" in text
    assert "light.den_wall_switch" not in text
