from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLIGHT_STATUS_PATH = ROOT / "packages" / "flight_status.yaml"


def _airport_delay_sensor_block() -> str:
    text = FLIGHT_STATUS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"      - name: Next Travel Flight Airport Delay\n(?P<block>.*?)(?=\n      - name: )",
        text,
        re.DOTALL,
    )
    assert match is not None
    return match.group("block")


def test_airport_delay_numeric_state_has_availability_guard() -> None:
    block = _airport_delay_sensor_block()

    assert "availability: >-" in block
    assert "origin not in ['', 'UNKNOWN', 'UNAVAILABLE']" in block
    assert "origin == tracked" in block
    assert "delay not in ['', 'unknown', 'unavailable']" in block


def test_airport_delay_state_template_is_numeric_only() -> None:
    block = _airport_delay_sensor_block()
    state_match = re.search(
        r"\n        state: >-\n(?P<state>.*?)(?=\n        attributes:)",
        block,
        re.DOTALL,
    )
    assert state_match is not None
    state_template = state_match.group("state")

    assert "unknown" not in state_template
    assert "unavailable" not in state_template
    assert "states('sensor.flightradar24_airport_departures_delay_average') | int(0)" in state_template
