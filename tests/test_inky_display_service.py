from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from inky_display.service import (
    PayloadCache,
    config_from_env,
    mqtt_connection_succeeded,
    process_payload,
    update_image_sink,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "inky_display" / "samples" / "owner_suite_night_preview.json"


def _sample_text() -> str:
    return SAMPLE_PATH.read_text(encoding="utf-8")


class RecordingSink:
    def __init__(self) -> None:
        self.images: list[bytes] = []

    def update(self, image: bytes) -> None:
        self.images.append(image)


def test_process_payload_renders_and_caches_last_good_image(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path)

    result = process_payload(_sample_text(), cache, "owner_suite")

    assert result.rendered is True
    assert result.reason == "rendered"
    assert result.image_path == cache.image_path
    assert cache.image_path.exists()
    assert cache.payload_path.read_text(encoding="utf-8") == _sample_text()
    assert cache.last_hash() == result.content_hash
    assert cache.restore_image() == cache.image_path.read_bytes()


def test_process_payload_updates_image_sink_when_rendered(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path)
    sink = RecordingSink()

    result = process_payload(_sample_text(), cache, "owner_suite", image_sink=sink)

    assert result.rendered is True
    assert sink.images == [cache.image_path.read_bytes()]


def test_process_payload_suppresses_duplicate_content_hash(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path)
    first = process_payload(_sample_text(), cache, "owner_suite")

    duplicate = process_payload(_sample_text(), cache, "owner_suite")

    assert first.rendered is True
    assert duplicate.rendered is False
    assert duplicate.reason == "duplicate"
    assert duplicate.content_hash == first.content_hash
    sink = RecordingSink()

    duplicate_with_sink = process_payload(_sample_text(), cache, "owner_suite", image_sink=sink)

    assert duplicate_with_sink.reason == "duplicate"
    assert sink.images == []


def test_process_payload_ignores_invalid_payload_without_overwriting_cache(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path)
    first = process_payload(_sample_text(), cache, "owner_suite")

    invalid = process_payload("{not-json", cache, "owner_suite")

    assert invalid.rendered is False
    assert invalid.reason == "invalid"
    assert cache.last_hash() == first.content_hash
    assert cache.restore_image() is not None


def test_process_payload_rejects_payload_for_another_display(tmp_path: Path) -> None:
    data = json.loads(_sample_text())
    data["display_id"] = "office"
    data["mode"] = "guest_info"

    result = process_payload(json.dumps(data), PayloadCache(tmp_path), "owner_suite")

    assert result.rendered is False
    assert result.reason == "wrong-display"


def test_config_from_env_uses_pi_service_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("INKY_DISPLAY_ID", "owner_suite")
    monkeypatch.setenv("INKY_MQTT_HOST", "mqtt.example.test")
    monkeypatch.setenv("INKY_MQTT_PORT", "1884")
    monkeypatch.setenv("INKY_MQTT_TOPIC", "home/inky/owner_suite/state")
    monkeypatch.setenv("INKY_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("INKY_MQTT_USERNAME", "inky")
    monkeypatch.setenv("INKY_MQTT_PASSWORD", "secret")
    monkeypatch.setenv("INKY_HARDWARE_ENABLED", "true")
    monkeypatch.setenv("INKY_PANEL_TYPE", "what")
    monkeypatch.setenv("INKY_PANEL_COLOR", "red")
    monkeypatch.setenv("INKY_ROTATION", "180")

    config = config_from_env()

    assert config.display_id == "owner_suite"
    assert config.mqtt_host == "mqtt.example.test"
    assert config.mqtt_port == 1884
    assert config.mqtt_topic == "home/inky/owner_suite/state"
    assert config.cache_dir == tmp_path
    assert config.mqtt_username == "inky"
    assert config.mqtt_password == "secret"
    assert config.hardware_enabled is True
    assert config.panel_type == "what"
    assert config.panel_color == "red"
    assert config.rotation == 180


def test_config_from_env_defaults_to_auto_panel_detection(monkeypatch) -> None:
    monkeypatch.delenv("INKY_PANEL_TYPE", raising=False)

    config = config_from_env()

    assert config.panel_type == "auto"


def test_update_image_sink_logs_and_continues_on_panel_failure(caplog) -> None:
    class FailingSink:
        def update(self, _image: bytes) -> None:
            raise OSError("panel offline")

    update_image_sink(FailingSink(), b"not-a-real-image")

    assert "Failed to update Inky panel" in caplog.text


def test_mqtt_connection_succeeded_accepts_paho_v2_reason_code() -> None:
    class SuccessReason:
        is_failure = False

    class FailureReason:
        is_failure = True

    assert mqtt_connection_succeeded(SuccessReason()) is True
    assert mqtt_connection_succeeded(FailureReason()) is False
    assert mqtt_connection_succeeded(0) is True
    assert mqtt_connection_succeeded(5) is False


def test_service_help_does_not_require_mqtt_dependency() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "inky_display.service", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--check-config" in result.stdout
