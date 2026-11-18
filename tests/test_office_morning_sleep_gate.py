from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIGHT_PATH = ROOT / "packages" / "light.yaml"
AUTOMATION_ID = "office_lights_morning_on_vacancy_off"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _morning_on_conditions() -> list[dict]:
    package = yaml.load(LIGHT_PATH.read_text(encoding="utf-8"), Loader=_Loader)
    automation = next(a for a in package["automation"] if a.get("id") == AUTOMATION_ID)
    for option in automation["action"][0]["choose"]:
        trigger_ids = [
            c.get("id") for c in option["conditions"] if c.get("condition") == "trigger"
        ]
        if trigger_ids and "office-occupied-motion" in trigger_ids[0]:
            return option["conditions"]
    raise AssertionError("Could not find the morning auto-on branch")


def test_morning_auto_on_never_runs_while_cpap_is_running() -> None:
    conditions = _morning_on_conditions()

    assert {
        "condition": "not",
        "conditions": [
            {
                "condition": "state",
                "entity_id": "binary_sensor.owner_suite_cpap_running",
                "state": "on",
            }
        ],
    } in conditions


def test_morning_auto_on_requires_both_office_sensors_while_bed_is_occupied() -> None:
    conditions = _morning_on_conditions()

    assert {
        "or": [
            {
                "condition": "not",
                "conditions": [
                    {
                        "condition": "state",
                        "entity_id": "binary_sensor.bed_occupied_debounced",
                        "state": "on",
                    }
                ],
            },
            {
                "and": [
                    {
                        "condition": "state",
                        "entity_id": "binary_sensor.office_motion_occupancy",
                        "state": "on",
                    },
                    {
                        "condition": "state",
                        "entity_id": "binary_sensor.office_occupancy_2",
                        "state": "on",
                    },
                ]
            },
        ]
    } in conditions
