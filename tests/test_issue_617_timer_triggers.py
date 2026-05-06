from __future__ import annotations

from pathlib import Path


FANS_PATH = Path(__file__).resolve().parents[1] / "packages" / "fans.yaml"

FAN_TIMER_MAP = {
    "timer.owner_suite_fan_timer": "fan.owner_suite",
    "timer.owner_suite_bathroom_exhaust_timer": "fan.owner_suite_bathroom_exhaust",
    "timer.office_ceiling_fan_timer": "fan.office_ceiling_fan",
    "timer.basement_bathroom_exhaust_timer": "fan.basement_bathroom_exhaust",
    "timer.den_ceiling_fan_timer": "fan.den_ceiling",
    "timer.guest_room_fan_timer": "fan.guest_room",
    "timer.guest_bathroom_exhaust_timer": "fan.guest_bathroom_exhaust",
}


def _fan_timer_block() -> str:
    lines = FANS_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index("  - alias: fan_off_when_timer_ends")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - alias: "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_fan_timer_automation_uses_ha_2026_5_timer_finished_triggers() -> None:
    block = _fan_timer_block()

    assert "event_type: timer.finished" not in block
    assert block.count("trigger: timer.finished") == len(FAN_TIMER_MAP)

    for timer_entity in FAN_TIMER_MAP:
        assert f"entity_id: {timer_entity}" in block


def test_fan_timer_automation_maps_trigger_entity_to_target_fan() -> None:
    block = _fan_timer_block()

    assert '{{ fan_map[trigger.entity_id] }}' in block
    assert "trigger.event.data.entity_id" not in block

    for timer_entity, fan_entity in FAN_TIMER_MAP.items():
        assert f"{timer_entity}: {fan_entity}" in block
