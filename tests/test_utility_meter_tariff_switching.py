"""Every tariffed utility meter must have its tariff select driven by automation.

A utility_meter with ``tariffs`` creates a ``select.<meter>`` that decides which
tariff sensor accumulates usage. If no automation switches it, that meter keeps
counting into whichever tariff it last had, and every cost derived from it is
wrong (this happened to ``select.weekly_ev_charging``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"

# Meter source prefix -> automation that owns its tariff selects.
SWITCHERS = {
    "sensor.house_electrical_meter": "switch_electrical_tariff",
    "_energy_added": "switch_ev_charging_tariff",
}


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant tags such as !secret/!include."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, _suffix, node: loader.construct_scalar(node)
    if isinstance(node, yaml.ScalarNode)
    else None,
)


def _package() -> dict:
    return yaml.load(UTILITIES_PATH.read_text(encoding="utf-8"), Loader=_Loader)


def _selected_entities(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        if node.get("action") == "select.select_option":
            target = node.get("target") or {}
            entity = target.get("entity_id") if isinstance(target, dict) else None
            entity = entity or node.get("entity_id") or (node.get("data") or {}).get("entity_id")
            found |= set(entity if isinstance(entity, list) else [entity] if entity else [])
        for value in node.values():
            found |= _selected_entities(value)
    elif isinstance(node, list):
        for item in node:
            found |= _selected_entities(item)
    return found


def _owner(source: str) -> str | None:
    for key, automation_id in SWITCHERS.items():
        if source.startswith(key) or source.endswith(key):
            return automation_id
    return None


def _tariffed_meters() -> list[tuple[str, str]]:
    meters = _package().get("utility_meter") or {}
    return sorted(
        (name, str(meter.get("source", "")))
        for name, meter in meters.items()
        if isinstance(meter, dict) and meter.get("tariffs") and _owner(str(meter.get("source", "")))
    )


@pytest.mark.parametrize(("meter", "source"), _tariffed_meters(), ids=lambda v: str(v))
def test_tariff_select_is_switched_by_its_automation(meter: str, source: str) -> None:
    automations = {a.get("id"): a for a in _package().get("automation", []) if isinstance(a, dict)}
    owner = automations[_owner(source)]
    assert f"select.{meter}" in _selected_entities(owner.get("action") or owner.get("actions"))


def test_weekly_ev_meter_is_covered() -> None:
    assert ("weekly_ev_charging" in {name for name, _ in _tariffed_meters()})
