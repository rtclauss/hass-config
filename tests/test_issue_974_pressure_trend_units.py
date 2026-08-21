from __future__ import annotations

from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"


def _trend_sensor_gradient(text: str, name: str) -> float:
    # Anchor on the exact trend-sensor block shape so this can't accidentally
    # match the unrelated `customize:` entry that shares the same entity name.
    marker = (
        f"      {name}:\n"
        "        entity_id: sensor.average_house_pressure\n"
        "        sample_duration: 10800\n"
        "        min_gradient: "
    )
    start = text.index(marker) + len(marker)
    end = text.index("\n", start)
    return float(text[start:end])


def test_pressure_trend_thresholds_are_reachable_in_inhg() -> None:
    # sensor.average_house_pressure reports inHg (confirmed live: device_class
    # atmospheric_pressure, unit inHg), but min_gradient — which the trend
    # platform reads as <source unit>/second — was calibrated for hPa/s.
    # 1 inHg = 33.8639 hPa, so the old values implied 0.54-1.98 inHg/hr
    # (18-67 hPa/hr) for the falling/quickly/v_rapidly tiers: rates never
    # once observed in 72h of real history (largest ~1hr rate was
    # -0.043 inHg/hr, ~1.45 hPa/hr). Those three tiers could never fire
    # (issue #974). Values must now be small enough to be reachable by real
    # weather-driven pressure changes.
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    thresholds = {
        "pressure_falling_v_rapidly": -0.0000162,
        "pressure_rising_v_rapidly": 0.0000162,
        "pressure_falling_quickly": -0.0000097,
        "pressure_rising_quickly": 0.0000097,
        "pressure_falling": -0.0000044,
        "pressure_rising": 0.0000044,
        "pressure_falling_slowly": -0.00000027,
        "pressure_rising_slowly": 0.00000027,
    }
    for name, expected in thresholds.items():
        actual = _trend_sensor_gradient(text, name)
        assert actual == expected, f"{name} min_gradient={actual}, expected {expected}"

    # The old hPa-calibrated magnitudes must be gone.
    for stale in ("-0.00055", "-0.00033", "-0.00015", "-0.000009\n"):
        assert stale not in text


def test_pressure_trend_severity_ordering_is_preserved() -> None:
    # Whatever the exact values, v_rapidly must stay the largest-magnitude
    # threshold and slowly the smallest, in both directions, so the four
    # tiers still escalate in the intended order.
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    v_rapidly = abs(_trend_sensor_gradient(text, "pressure_falling_v_rapidly"))
    quickly = abs(_trend_sensor_gradient(text, "pressure_falling_quickly"))
    falling = abs(_trend_sensor_gradient(text, "pressure_falling"))
    slowly = abs(_trend_sensor_gradient(text, "pressure_falling_slowly"))

    assert v_rapidly > quickly > falling > slowly > 0
