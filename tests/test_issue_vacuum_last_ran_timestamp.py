from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLEANING_PATH = ROOT / "packages" / "cleaning.yaml"


def test_vacuum_last_ran_is_a_timestamp_sensor_without_state_class() -> None:
    text = CLEANING_PATH.read_text(encoding="utf-8")

    assert 'unique_id: vacuum_last_ran' in text
    assert 'device_class: timestamp' in text
    assert '{{ now().isoformat() }}' in text
    assert 'state_class:' not in text.split('unique_id: vacuum_last_ran', 1)[1].split(
        '########################', 1
    )[0]
