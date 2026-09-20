"""Regression coverage for reusable privacy and context automation guards."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARDS_PATH = ROOT / "packages" / "automation_guards.yaml"


def _guards_text() -> str:
    return GUARDS_PATH.read_text(encoding="utf-8")


def _guard_block(name: str) -> str:
    text = _guards_text()
    start = text.index(f"- name: {name}")
    next_guard = text.find("\n      - name: ", start + 1)
    return text[start:] if next_guard == -1 else text[start:next_guard]


def test_all_guard_entities_have_stable_ids_and_customization() -> None:
    text = _guards_text()

    for name in (
        "intrusive_automations_allowed",
        "owner_actively_working",
        "sleep_protection_active",
        "house_ready_for_bed",
        "arrival_welcome_needed",
    ):
        assert f"binary_sensor.{name}:" in text
        assert f"- name: {name}" in text
        assert f"unique_id: {name}" in text


def test_intrusive_guard_has_privacy_and_sleep_vetoes() -> None:
    block = _guard_block("intrusive_automations_allowed")

    for entity_id in (
        "person.ryan",
        "input_select.house_mode",
        "binary_sensor.bed_occupied_debounced",
        "input_boolean.guest_mode",
        "binary_sensor.guest_room_occupancy_2",
    ):
        assert entity_id in block


def test_work_guard_is_debounced_and_guest_safe() -> None:
    block = _guard_block("owner_actively_working")

    assert "binary_sensor.workday_sensor" in block
    assert "binary_sensor.office_confident_occupancy" in block
    assert "input_boolean.guest_mode" in block
    assert 'delay_on: "00:05:00"' in block
    assert 'delay_off: "00:03:00"' in block


def test_sleep_guard_covers_bed_and_explicit_sleep_modes() -> None:
    block = _guard_block("sleep_protection_active")

    assert "binary_sensor.bed_occupied_debounced" in block
    assert "['in_bed', 'asleep']" in block


def test_bedtime_guard_preserves_guest_context_and_verifies_climate() -> None:
    block = _guard_block("house_ready_for_bed")

    for entity_id in (
        "lock.front_door_lock",
        "cover.garage_door",
        "cover.owner_suite_blinds_ha",
        "input_boolean.guest_mode",
        "binary_sensor.guest_room_occupancy_2",
        "climate.my_ecobee",
    ):
        assert entity_id in block
    assert "guest_context and climate_preset == 'Guest Sleep'" in block
    assert "not guest_context" in block


def test_arrival_guard_is_a_predicate_not_an_action() -> None:
    block = _guard_block("arrival_welcome_needed")

    assert "sun.sun" in block
    assert "binary_sensor.hall_main_foyer_motion_occupancy" in block
    assert "light.hall_foyer_switch" in block
    assert "action:" not in block
