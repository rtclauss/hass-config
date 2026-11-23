"""The curling season toggle must target automations that actually exist."""

from __future__ import annotations

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
CURLING_PATH = ROOT / "packages" / "curling.yaml"


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant tags such as !secret/!include."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, _suffix, node: loader.construct_scalar(node)
    if isinstance(node, yaml.ScalarNode)
    else None,
)


def _slug(alias: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", alias.lower()).strip("_")


def test_season_toggle_targets_defined_automations() -> None:
    package = yaml.load(CURLING_PATH.read_text(encoding="utf-8"), Loader=_Loader)
    automations = [a for a in package["automation"] if isinstance(a, dict)]
    defined = {f"automation.{_slug(a['alias'])}" for a in automations}
    toggle = next(a for a in automations if a["id"] == "toggle_curling_automations_on_season_change")
    targets = [step["data"]["entity_id"] for step in toggle["action"]]

    assert targets, "season toggle has no targets"
    missing = [t for t in targets if t not in defined]
    assert not missing, f"season toggle targets undefined automations: {missing}"
