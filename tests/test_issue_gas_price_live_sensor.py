from __future__ import annotations

from pathlib import Path


UTILITIES_PATH = Path(__file__).resolve().parents[1] / "packages" / "utilities.yaml"


def test_gas_price_live_sensor_guards_missing_scraped_matches() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    assert "name: Woodbury Weekly Regular Gas Price Live" in text
    assert "regex_findall_index(" not in text
    assert "regex_findall('Week Ago Avg\\\\.\\\\s*\\\\$([0-9]+\\\\.[0-9]+)')" in text
    assert "{{ matches[0] | float(default=0) | round(2) }}" in text
    assert "{{ none }}" in text
