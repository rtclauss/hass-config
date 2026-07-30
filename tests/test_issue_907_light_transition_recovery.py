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
        "turn_on_office_lamp_when_work_tp_camera_inactive": 1,
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


# Automations that must still act on a recovery into the target state, because
# the action is protective rather than intrusive. #907 explicitly carves out
# "recovery-sensitive automations where current-state reconciliation may be
# intentional". These accept the real edge plus unavailable/unknown -> target.
RECOVERY_SENSITIVE = {
    # Darkens the office and pauses house audio because a camera is live. A
    # reload mid-meeting recovers unavailable -> on; dropping that would leave
    # the ceiling on and audio playing through the call.
    "turn_off_office_lamp_when_work_tp_camera_active",
}

RECOVERY_STATES = ("unavailable", "unknown")


def test_binary_light_triggers_require_real_state_transitions() -> None:
    for relative_path, automations in SCOPED_AUTOMATIONS.items():
        path = ROOT / relative_path

        for automation_id, expected_trigger_count in automations.items():
            if automation_id in RECOVERY_SENSITIVE:
                continue
            triggers = _binary_state_triggers(_automation_block(path, automation_id))
            assert len(triggers) == expected_trigger_count, automation_id

            for trigger in triggers:
                target_state = re.search(r'^\s+to: "(on|off)"$', trigger, re.MULTILINE)
                assert target_state is not None
                expected_from = "off" if target_state.group(1) == "on" else "on"
                assert f'from: "{expected_from}"' in trigger, (automation_id, trigger)


def test_recovery_sensitive_automations_still_act_on_entity_recovery() -> None:
    # The camera-active automation must fire when a reload reveals an already
    # active camera, not only on a clean off->on edge.
    block = _automation_block(ROOT / "packages/workday.yaml", "turn_off_office_lamp_when_work_tp_camera_active")
    triggers = _binary_state_triggers(block)

    assert len(triggers) == SCOPED_AUTOMATIONS["packages/workday.yaml"][
        "turn_off_office_lamp_when_work_tp_camera_active"
    ]
    for trigger in triggers:
        assert re.search(r'^\s+to: "on"$', trigger, re.MULTILINE), trigger
        # The real edge is still accepted...
        assert '- "off"' in trigger, trigger
        # ...and so is a recovery that reveals the camera already in use.
        for state in RECOVERY_STATES:
            assert f'- "{state}"' in trigger, (state, trigger)


def test_camera_inactive_automation_requires_a_sustained_off_state() -> None:
    # The counterpart turns the ceiling back ON, so a recovery into `off` must
    # not trigger it — that would light the room unbidden after a restart. A
    # sustained-off guard also filters the camera's sub-second off/on flaps.
    block = _automation_block(ROOT / "packages/workday.yaml", "turn_on_office_lamp_when_work_tp_camera_inactive")
    triggers = _binary_state_triggers(block)

    assert len(triggers) == 1
    trigger = triggers[0]
    assert 'from: "on"' in trigger
    assert re.search(r"^\s+for:\n\s+seconds: 15$", trigger, re.MULTILINE), trigger
    for state in RECOVERY_STATES:
        assert state not in trigger, (state, trigger)
