from __future__ import annotations

from pathlib import Path


PARASOLL_PATH = Path(__file__).resolve().parents[1] / "packages" / "parasoll_fix.yaml"


def test_parasoll_configure_state_uses_csv_within_ha_input_text_limit() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "Compact CSV: <last4_ieee>:<mod_hour>,..." in text
    assert "max: 255" in text
    assert 'initial: ""' in text
    assert "{{ ns.pairs | join(',') }}" in text
    assert "| tojson" not in text


def test_parasoll_configure_state_keeps_legacy_json_read_compatibility() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "raw.startswith('{')" in text
    assert "raw | from_json" in text
    assert "store.items()" in text


def test_parasoll_csv_state_has_room_for_current_device_count() -> None:
    device_count = 20
    sample_pairs = [f"{index:04x}:9999" for index in range(device_count)]
    assert len(",".join(sample_pairs)) < 255


def test_parasoll_auto_reconfigure_queue_covers_current_fleet_burst() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "mode: queued" in text
    assert "max: 30" in text
    assert "full fleet burst plus headroom" in text


def test_parasoll_contact_change_ignores_startup_restores() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert 'id: contact_change' in text
    assert 'from:\n          - "on"\n          - "off"' in text
    assert 'to:\n          - "on"\n          - "off"' in text


def test_parasoll_contact_change_keeps_restored_south_middle_contact() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "binary_sensor.owner_suite_bathroom_bay_south_middle_window_contact" in text


def test_parasoll_ias_ok_checks_ep2_not_ep1() -> None:
    # PARASOLL's ssIasZone cluster lives on endpoint 2 (confirmed by Z2M Bind tab
    # "Source endpoint 2: ssIasZone").  Checking ep1 would always return False,
    # causing _needs_configure to be True on every contact_change — the original bug.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "_ep2_bindings" in text
    assert "'ssIasZone' in _ep2_bindings" in text
    # Ensure we are NOT using ep1 for the IAS check
    assert "'ssIasZone' in _ep1_bindings" not in text
