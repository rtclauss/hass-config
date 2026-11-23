"""Light actions must use color_temp_kelvin, not the removed kelvin/color_temp keys.

Home Assistant's light.turn_on schema no longer accepts ``kelvin`` or the
mired-based ``color_temp``; a call that passes either fails validation when the
action runs, silently breaking the automation branch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REMOVED_KEYS = {"kelvin", "color_temp"}
LIGHT_ACTIONS = {"light.turn_on", "light.toggle"}


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant tags such as !secret/!include."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, _suffix, node: loader.construct_scalar(node)
    if isinstance(node, yaml.ScalarNode)
    else None,
)


def _config_files() -> list[Path]:
    return [ROOT / "scripts.yaml", *sorted((ROOT / "packages").glob("*.yaml"))]


def _offenders(node, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        action = node.get("action") or node.get("service")
        if isinstance(action, str) and action in LIGHT_ACTIONS:
            for block in (node.get("data"), node.get("data_template")):
                if isinstance(block, dict):
                    found += [f"{path}: {action} uses {key}" for key in REMOVED_KEYS & block.keys()]
        for value in node.values():
            found += _offenders(value, path)
    elif isinstance(node, list):
        for item in node:
            found += _offenders(item, path)
    return found


@pytest.mark.parametrize("path", _config_files(), ids=lambda p: p.name)
def test_light_actions_use_color_temp_kelvin(path: Path) -> None:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    assert _offenders(data, path.name) == []


def test_dining_room_double_tap_uses_color_temp_kelvin() -> None:
    text = (ROOT / "packages" / "zigbee_zwave.yaml").read_text(encoding="utf-8")
    block = text[text.index("id: dining_room_switch_actions") :]
    block = block[: block.index("\n  - id:", 1)]
    assert block.count("color_temp_kelvin: >-") == 2
