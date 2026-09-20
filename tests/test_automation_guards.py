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
        "guest_privacy_protection_active",
        "automatic_cleaning_allowed",
        "owner_suite_wake_ready",
        "overnight_path_lighting_allowed",
        "house_away_secure",
        "high_power_appliance_running",
        "mail_attention_needed",
        "air_quality_action_needed",
        "ev_charge_needed_before_departure",
        "inky_display_attention_needed",
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


def test_guest_and_automatic_cleaning_guards_preserve_privacy_and_pet_policy() -> None:
    guest_block = _guard_block("guest_privacy_protection_active")
    cleaning_block = _guard_block("automatic_cleaning_allowed")

    assert "input_boolean.guest_mode" in guest_block
    assert "binary_sensor.guest_room_occupancy_2" in guest_block
    for entity_id in (
        "input_select.vacuum_pet_policy",
        "input_boolean.guest_mode",
        "binary_sensor.bed_occupied_debounced",
        "binary_sensor.den_doors_contact",
    ):
        assert entity_id in cleaning_block
    assert "'Unattended'" in cleaning_block


def test_wake_and_path_guards_are_tied_to_existing_sleep_policy_inputs() -> None:
    wake_block = _guard_block("owner_suite_wake_ready")
    path_block = _guard_block("overnight_path_lighting_allowed")

    for entity_id in (
        "binary_sensor.workday_sensor",
        "binary_sensor.planned_vacation_calendar",
        "binary_sensor.bed_occupied_debounced",
        "input_boolean.wakeup_alarm_firing",
    ):
        assert entity_id in wake_block
    assert "binary_sensor.sleep_protection_active" in path_block
    assert "input_boolean.guest_mode" in path_block


def test_house_appliance_mail_and_air_guards_use_normalized_entities() -> None:
    away_block = _guard_block("house_away_secure")
    appliance_block = _guard_block("high_power_appliance_running")
    mail_block = _guard_block("mail_attention_needed")
    air_block = _guard_block("air_quality_action_needed")

    assert "lock.front_door_lock" in away_block
    assert "cover.garage_door" in away_block
    for entity_id in (
        "binary_sensor.dishwasher_running",
        "binary_sensor.dryer_running",
        "binary_sensor.washing_machine_running",
    ):
        assert entity_id in appliance_block
    assert "input_select.mail_package_delivery_state" in mail_block
    assert "sensor.average_house_humidity" in air_block
    assert 'delay_on: "00:10:00"' in air_block


def test_ev_and_inky_guards_are_conservative_and_event_source_based() -> None:
    ev_block = _guard_block("ev_charge_needed_before_departure")
    inky_block = _guard_block("inky_display_attention_needed")

    assert "input_number.ev_departure_minimum_battery" in _guards_text()
    for entity_id in (
        "input_boolean.tesla_managed_departure_active",
        "input_number.tesla_managed_departure_ts",
        "sensor.nigori_battery",
        "binary_sensor.nigori_charging",
    ):
        assert entity_id in ev_block
    assert "sensor.nws_dakota_county_alerts_alerts_are_active" in inky_block
    assert "cover.garage_door" in inky_block
