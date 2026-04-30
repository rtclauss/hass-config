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
