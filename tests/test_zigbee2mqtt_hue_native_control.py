from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ZIGBEE2MQTT_CONFIG_PATH = REPO_ROOT / "zigbee2mqtt" / "configuration.example.yaml"


def _section_lines(section_name: str) -> list[str]:
    lines = ZIGBEE2MQTT_CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{section_name}:") + 1
    section: list[str] = []

    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        section.append(line)

    return section


def test_hue_native_control_is_enabled_by_default_for_devices() -> None:
    device_options = _section_lines("device_options")

    assert "  hue_native_control: true" in device_options


def test_white_only_hue_example_filters_stale_color_cache() -> None:
    configuration = yaml.safe_load(
        ZIGBEE2MQTT_CONFIG_PATH.read_text(encoding="utf-8")
    )
    devices = configuration["devices"]
    white_only_bulb = next(
        device
        for device in devices.values()
        if device["friendly_name"] == "Owner Suite/Lamp Bulb 1"
    )

    assert white_only_bulb["hue_native_control"] is False
    assert white_only_bulb["filtered_attributes"] == ["^color_(mode|temp)$"]
    assert white_only_bulb["filtered_cache"] == ["^color_(mode|temp)$"]


def _group_blocks() -> dict[str, list[str]]:
    groups = _section_lines("groups")
    blocks: dict[str, list[str]] = {}
    current_group: list[str] = []

    for line in groups:
        if line.startswith("  '"):
            if current_group:
                _add_group_block(blocks, current_group)
            current_group = [line]
        elif current_group:
            current_group.append(line)

    if current_group:
        _add_group_block(blocks, current_group)

    return blocks


def _add_group_block(blocks: dict[str, list[str]], group: list[str]) -> None:
    for line in group:
        if "friendly_name:" not in line:
            continue
        friendly_name = line.split("friendly_name:", 1)[1].strip()
        blocks[friendly_name] = group
        return


def test_switch_sync_hue_groups_do_not_opt_in_to_group_native_control() -> None:
    groups = _group_blocks()

    for friendly_name in ("Deck/Hue", "Outside/Front Hue"):
        assert friendly_name in groups
        assert "    hue_native_control: true" not in groups[friendly_name]
