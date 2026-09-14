from __future__ import annotations

from pathlib import Path

import pytest

from water_meter import config


def test_connection_config_from_env_uses_documented_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(__import__("os").environ):
        if name.startswith("WATER_METER_"):
            monkeypatch.delenv(name, raising=False)

    connection = config.connection_config_from_env()

    assert connection.mqtt_host == "localhost"
    assert connection.mqtt_port == 1883
    assert connection.light_topic == "zigbee2mqtt/water_meter_flash/set"
    assert connection.light_brightness == config.DEFAULT_LIGHT_BRIGHTNESS
    assert connection.reading_topic == "waterreader/sensor/water_meter/state"
    assert connection.status_topic == "waterreader/sensor/water_meter/status"
    assert connection.discovery_topic == "homeassistant/sensor/water_meter/config"
    assert (
        connection.capture_failure_reboot_threshold
        == config.DEFAULT_CAPTURE_FAILURE_REBOOT_THRESHOLD
    )
    # Empty host is what lets ocr.read_digits skip the vision-LLM tier
    # entirely for deployments that haven't configured one.
    assert connection.vlm_host == ""
    assert connection.vlm_model == "qwen3-vl:4b"
    assert connection.vlm_timeout_seconds == 480.0


def test_connection_config_from_env_honors_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATER_METER_MQTT_HOST", "homeassistant.local")
    monkeypatch.setenv("WATER_METER_MQTT_PORT", "8883")
    monkeypatch.setenv("WATER_METER_LIGHT_TOPIC", "zigbee2mqtt/Basement/Meter Light/set")
    monkeypatch.setenv("WATER_METER_LIGHT_BRIGHTNESS", "153")
    monkeypatch.setenv("WATER_METER_CAPTURE_FAILURE_REBOOT_THRESHOLD", "5")
    monkeypatch.setenv("WATER_METER_VLM_HOST", "truenas.local:30068")
    monkeypatch.setenv("WATER_METER_VLM_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("WATER_METER_VLM_TIMEOUT_SECONDS", "300")

    connection = config.connection_config_from_env()

    assert connection.mqtt_host == "homeassistant.local"
    assert connection.mqtt_port == 8883
    assert connection.light_topic == "zigbee2mqtt/Basement/Meter Light/set"
    assert connection.light_brightness == 153
    assert connection.capture_failure_reboot_threshold == 5
    assert connection.vlm_host == "truenas.local:30068"
    assert connection.vlm_model == "qwen3-vl:8b"
    assert connection.vlm_timeout_seconds == 300.0


def test_calibration_config_from_dict_requires_roi() -> None:
    with pytest.raises(ValueError, match="roi"):
        config.calibration_config_from_dict({})


def test_calibration_config_from_dict_fills_defaults() -> None:
    calibration = config.calibration_config_from_dict(
        {"roi": [10, 20, 300, 60], "digit_boxes": [[10, 20, 30, 60], [40, 20, 30, 60]]}
    )

    assert calibration.roi == (10, 20, 300, 60)
    assert calibration.digit_boxes == ((10, 20, 30, 60), (40, 20, 30, 60))
    assert calibration.digit_count == 2
    assert calibration.excluded_digit_indexes == ()
    assert calibration.warmup_seconds == config.DEFAULT_LIGHT_WARMUP_SECONDS
    assert calibration.history_limit == config.DEFAULT_HISTORY_LIMIT
    assert calibration.decimal_places == 0
    assert calibration.low_confidence_ok_indexes == ()


def test_calibration_config_round_trips_through_json_file(tmp_path: Path) -> None:
    calibration = config.calibration_config_from_dict(
        {
            "roi": [10, 20, 300, 60],
            "digit_boxes": [[10, 20, 30, 60], [40, 20, 30, 60]],
            "excluded_digit_indexes": [1],
            "max_gallons_per_interval": 250.0,
            "decimal_places": 1,
            "low_confidence_ok_indexes": [0],
        }
    )
    path = tmp_path / "calibration.json"

    config.save_calibration_config(path, calibration)
    restored = config.load_calibration_config(path)

    assert restored == calibration
    assert restored.decimal_places == 1
    assert restored.low_confidence_ok_indexes == (0,)
    assert "yaml" not in path.read_text(encoding="utf-8").lower()


def test_load_calibration_config_rejects_non_mapping_json(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        config.load_calibration_config(path)
