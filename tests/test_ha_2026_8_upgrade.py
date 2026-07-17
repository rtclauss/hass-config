from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIGURATION_PATH = ROOT / "configuration.yaml"


def _lovelace_block() -> str:
    text = CONFIGURATION_PATH.read_text(encoding="utf-8")
    match = re.search(r"^lovelace:\n(.*?)(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError("Could not find lovelace block in configuration.yaml")
    return match.group(0)


def test_lovelace_yaml_resources_use_resource_mode() -> None:
    block = _lovelace_block()

    assert "\n  mode: yaml\n" not in block
    assert "\n  resource_mode: yaml\n" in block


def test_yaml_dashboards_are_declared_individually() -> None:
    block = _lovelace_block()

    assert re.search(
        r"^    db-guest:\n"
        r"      mode: yaml\n"
        r"      title: Guest\n"
        r"      icon: mdi:bag-checked\n"
        r"      show_in_sidebar: false\n"
        r"      filename: ui-guest.yaml$",
        block,
        re.MULTILINE,
    )
