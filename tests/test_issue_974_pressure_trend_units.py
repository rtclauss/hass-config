from __future__ import annotations

from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"


def _trend_sensor_gradient(text: str, name: str, sample_duration: int = 10800) -> float:
    # Anchor on the exact trend-sensor block shape so this can't accidentally
    # match the unrelated `customize:` entry that shares the same entity name.
    marker = (
        f"      {name}:\n"
        "        entity_id: sensor.average_house_pressure\n"
        f"        sample_duration: {sample_duration}\n"
        "        max_samples: 500\n"
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


def test_pressure_trend_sensors_set_max_samples() -> None:
    # Codex P1: the trend platform's config schema defaults max_samples to 2
    # regardless of sample_duration, so without an explicit max_samples every
    # one of these sensors — including the 3-hour ones — would compute its
    # gradient from whichever 2 samples happen to be in the buffer, which can
    # still be milliseconds apart during a burst (the same instability
    # behind the temperature derivative spike in #973).
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    assert text.count("sample_duration: 10800\n        max_samples: 500\n") == 8
    assert text.count("sample_duration: 1800\n        max_samples: 500\n") == 2


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


def test_pressure_fast_short_window_sensor_is_above_the_measured_noise_floor() -> None:
    # 30 days of live history showed indoor 30-minute rates spiking to
    # ~6.6 hPa/hr from ordinary multi-sensor-mean noise alone (a milder
    # version of the burst effect behind #973). The fast tier must sit
    # meaningfully above that so it doesn't flap on routine noise, while
    # still being far below the frontal-scale 3-hour thresholds — a short
    # window needs a much higher instantaneous rate to represent a real,
    # fast-developing event.
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    falling_fast = _trend_sensor_gradient(text, "pressure_falling_fast", sample_duration=1800)
    rising_fast = _trend_sensor_gradient(text, "pressure_rising_fast", sample_duration=1800)
    assert falling_fast == -0.000082
    assert rising_fast == 0.000082

    measured_30min_noise_ceiling_inhg_per_s = 0.0001962 / 3600  # ~6.6 hPa/hr
    assert abs(falling_fast) > measured_30min_noise_ceiling_inhg_per_s * 1.25

    v_rapidly = abs(_trend_sensor_gradient(text, "pressure_falling_v_rapidly"))
    assert abs(falling_fast) > v_rapidly, (
        "a 30-minute window needs a higher instantaneous rate than the "
        "3-hour v_rapidly tier to represent an equally significant event"
    )


def test_pressure_binary_sensors_have_no_invalid_device_class() -> None:
    # "pressure" is not a valid binary_sensor device_class (only sensor
    # entities have pressure/atmospheric_pressure device classes) — see
    # https://www.home-assistant.io/integrations/binary_sensor/. Reconciled
    # away in #974; these are trend/direction flags and don't need one.
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    names = [
        "pressure_falling",
        "pressure_falling_quickly",
        "pressure_falling_slowly",
        "pressure_falling_v_rapidly",
        "pressure_falling_fast",
        "pressure_rising",
        "pressure_rising_quickly",
        "pressure_rising_slowly",
        "pressure_rising_v_rapidly",
        "pressure_rising_fast",
    ]
    for name in names:
        marker = f"binary_sensor.{name}:\n      <<: *customize\n      friendly_name: "
        start = text.index(marker)
        end = text.index("\n\n", start)
        block = text[start:end]
        assert "device_class:" not in block, f"binary_sensor.{name} should not set device_class"


def test_average_house_pressure_device_class_matches_its_sources() -> None:
    # The 9 _tph_pressure sensors it averages all report device_class:
    # atmospheric_pressure; the aggregate had drifted to device_class:
    # pressure instead (#974).
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    marker = (
        "sensor.average_house_pressure:\n"
        "      <<: *customize\n"
        '      friendly_name: "Average House Pressure"\n'
    )
    start = text.index(marker) + len(marker)
    end = text.index("icon: mdi:gauge", start)
    block = text[start:end]
    assert "device_class: atmospheric_pressure" in block


def test_pressure_trends_group_includes_the_fast_sensors() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    start = text.index("pressure_trends:")
    end = text.index("\n\n", start)
    block = text[start:end]
    assert "binary_sensor.pressure_falling_fast" in block
    assert "binary_sensor.pressure_rising_fast" in block


def test_window_pressure_alert_automation_includes_the_fast_sensor() -> None:
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]
    assert "binary_sensor.pressure_falling_fast" in block
    assert "binary_sensor.pressure_falling_quickly" in block
    assert "binary_sensor.pressure_falling_v_rapidly" in block
