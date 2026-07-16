from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCOPED_AUTOMATIONS = {
    "packages/light.yaml": {
        "front_door_light_auto_toggle": 3,
        "garage_entry_door_light_auto_toggle": 3,
        "kitchen_lights_toggle": 2,
        "owner_suite_bath_light_auto_toggle": 2,
        "owner_suite_light_auto_off": 1,
        "turn_off_basement_light_when_dark_in_room": 1,
        "office_lights_morning_on_vacancy_off": 5,
    },
    "packages/workday.yaml": {
        "turn_off_office_lamp_when_work_tp_camera_active": 2,
        "turn_on_office_lamp_when_work_tp_camera_inactive": 2,
    },
    "packages/zigbee_zwave.yaml": {
        "side_of_bed_toggles": 8,
    },
}


def _automation_block(path: Path, automation_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - (?:id|alias): {re.escape(automation_id)}\n(.*?)(?=^  - (?:id|alias): |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")
    return match.group(0)


def _binary_state_triggers(block: str) -> list[str]:
    trigger_section = block.split("    trigger:\n", maxsplit=1)[1].split("    condition", maxsplit=1)[0]
    trigger_section = trigger_section.split("    action:\n", maxsplit=1)[0]
    triggers = re.findall(
        r"^      - trigger: state\n(.*?)(?=^      - trigger: |\Z)",
        trigger_section,
        re.MULTILINE | re.DOTALL,
    )
    return [
        trigger
        for trigger in triggers
        if "binary_sensor." in trigger and re.search(r'^\s+to: "(?:on|off)"$', trigger, re.MULTILINE)
    ]


def test_binary_light_triggers_require_real_state_transitions() -> None:
    for relative_path, automations in SCOPED_AUTOMATIONS.items():
        path = ROOT / relative_path

        for automation_id, expected_trigger_count in automations.items():
            triggers = _binary_state_triggers(_automation_block(path, automation_id))
            assert len(triggers) == expected_trigger_count, automation_id

            for trigger in triggers:
                target_state = re.search(r'^\s+to: "(on|off)"$', trigger, re.MULTILINE)
                assert target_state is not None
                expected_from = "off" if target_state.group(1) == "on" else "on"
                assert f'from: "{expected_from}"' in trigger, (automation_id, trigger)
