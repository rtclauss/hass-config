from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _package() -> dict:
    return yaml.load((ROOT / "packages" / "diffusers.yaml").read_text(), _Loader)


def _automation(pkg: dict, automation_id: str) -> dict:
    return next(a for a in pkg["automation"] if a["id"] == automation_id)


def test_dining_room_diffuser_is_pulsed_not_grouped() -> None:
    pkg = _package()
    assert "switch.dining_room_cat_diffuser" not in pkg["group"]["diffusers"]["entities"]
    assert "switch.owner_suite_cat_diffuser" in pkg["group"]["diffusers"]["entities"]


def test_dining_room_pulse_is_ten_minutes_on_per_hour() -> None:
    pkg = _package()
    on = _automation(pkg, "dining_room_diffuser_pulse_on")
    off = _automation(pkg, "dining_room_diffuser_pulse_off")
    assert on["trigger"][0]["minutes"] == "0"
    assert off["trigger"][0]["minutes"] == "10"
    assert on["action"][0]["action"] == "switch.turn_on"
    assert off["action"][0]["action"] == "switch.turn_off"
    entities = {c.get("entity_id") for c in on["condition"]}
    assert {"input_boolean.trip", "binary_sensor.planned_vacation_calendar"} <= entities
    # Sleep/wake participation: pulses only while the diffuser set is on, and a
    # goodnight (group off) or a missed :10 across a restart also turns it off.
    assert "group.diffusers" in entities
    triggers = {t["trigger"] for t in off["trigger"]}
    assert {"time_pattern", "state", "homeassistant"} <= triggers
