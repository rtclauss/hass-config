from __future__ import annotations

import json
import sys
import threading
import types
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from water_meter import correction_listener, sanity
from water_meter.config import CalibrationConfig, ConnectionConfig


def _install_fake_paho(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    published: list[dict] = []

    def _multiple(messages: list[dict], **kwargs: object) -> None:
        published.extend(messages)

    fake_publish = types.ModuleType("paho.mqtt.publish")
    fake_publish.multiple = _multiple  # type: ignore[attr-defined]
    fake_mqtt = types.ModuleType("paho.mqtt")
    fake_mqtt.publish = fake_publish  # type: ignore[attr-defined]
    fake_paho = types.ModuleType("paho")
    fake_paho.mqtt = fake_mqtt  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "paho", fake_paho)
    monkeypatch.setitem(sys.modules, "paho.mqtt", fake_mqtt)
    monkeypatch.setitem(sys.modules, "paho.mqtt.publish", fake_publish)
    return published


def _connection(tmp_path: Path) -> ConnectionConfig:
    return ConnectionConfig(
        mqtt_host="broker",
        mqtt_port=1883,
        mqtt_username="",
        mqtt_password="",
        light_topic="zigbee2mqtt/water_meter_flash/set",
        reading_topic="waterreader/sensor/water_meter/state",
        last_reading_time_topic="waterreader/sensor/water_meter/last_reading_time",
        status_topic="waterreader/sensor/water_meter/status",
        discovery_topic="homeassistant/sensor/water_meter/config",
        camera_device="/dev/fake",
        calibration_path=tmp_path / "calibration.json",
        templates_dir=tmp_path / "templates",
        state_dir=tmp_path / "state",
        image_dir=tmp_path / "images",
    )


NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_apply_correction_writes_state_and_publishes_mqtt_even_for_a_decrease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deliberately allows a decrease - overriding the monotonic safety net
    # is the entire point (fixing an inflated bad baseline).
    published = _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=219118.0, timestamp=NOW.isoformat())
    )

    correction_listener.apply_correction(connection, 214170.0, now=NOW)

    saved = sanity.load_last_good(connection.state_dir)
    assert saved is not None
    assert saved.value == 214170.0

    by_topic = {m["topic"]: m["payload"] for m in published}
    assert by_topic["waterreader/sensor/water_meter/state"] == "214170.0"
    assert by_topic["waterreader/sensor/water_meter/status"] == "ok"


def _start_test_server(
    connection: ConnectionConfig, token: str
) -> tuple[object, str, threading.Thread]:
    handler_cls = correction_listener._make_handler(connection, token)
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    return server, base_url, thread


def _post(base_url: str, token: str | None, body: object) -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"{base_url}/correction",
        data=json.dumps(body).encode("utf-8") if body is not None else b"",
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_listener_applies_a_valid_authenticated_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=100.0, timestamp=NOW.isoformat())
    )
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, body = _post(base_url, "secret-token", {"value": 214170.0})
        assert status == 200
        assert json.loads(body) == {"ok": True, "value": 214170.0}
        saved = sanity.load_last_good(connection.state_dir)
        assert saved is not None
        assert saved.value == 214170.0
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_listener_rejects_a_request_with_the_wrong_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=100.0, timestamp=NOW.isoformat())
    )
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, _ = _post(base_url, "wrong-token", {"value": 214170.0})
        assert status == 401
        saved = sanity.load_last_good(connection.state_dir)
        assert saved is not None
        assert saved.value == 100.0  # unchanged
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_listener_rejects_an_out_of_range_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=100.0, timestamp=NOW.isoformat())
    )
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, _ = _post(base_url, "secret-token", {"value": -5.0})
        assert status == 400
        status, _ = _post(base_url, "secret-token", {"value": 99_999_999_999.0})
        assert status == 400
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_listener_rejects_malformed_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=100.0, timestamp=NOW.isoformat())
    )
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, _ = _post(base_url, "secret-token", {"not_value": 1})
        assert status == 400
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_main_refuses_to_start_without_a_correction_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATER_METER_CORRECTION_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        correction_listener.main()


def _calibration(**overrides: object) -> CalibrationConfig:
    defaults: dict[str, object] = dict(
        roi=(0, 0, 10, 10),
        digit_boxes=((0, 0, 5, 5),),
        digit_count=8,
        excluded_digit_indexes=(),
        warmup_seconds=0.0,
        frames_to_grab=1,
        frames_to_discard=0,
        max_gallons_per_interval=500.0,
        stuck_after_hours=24.0,
        history_limit=5,
        ssocr_args=(),
        decimal_places=1,
    )
    defaults.update(overrides)
    return CalibrationConfig(**defaults)  # type: ignore[arg-type]


def _get(base_url: str, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_get_crop_returns_the_latest_crop_image_with_a_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    connection.image_dir.mkdir(parents=True, exist_ok=True)
    (connection.image_dir / "latest_crop.jpg").write_bytes(b"fake-jpeg-bytes")
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, body = _get(base_url, "/crop?token=secret-token")
        assert status == 200
        assert body == b"fake-jpeg-bytes"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_get_crop_rejects_the_wrong_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    connection.image_dir.mkdir(parents=True, exist_ok=True)
    (connection.image_dir / "latest_crop.jpg").write_bytes(b"fake-jpeg-bytes")
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, _ = _get(base_url, "/crop?token=wrong-token")
        assert status == 401
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_get_crop_404s_when_no_crop_has_been_saved_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    server, base_url, thread = _start_test_server(connection, "secret-token")
    try:
        status, _ = _get(base_url, "/crop?token=secret-token")
        assert status == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_apply_correction_saves_a_dynamic_fewshot_example_when_calibration_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    connection.image_dir.mkdir(parents=True, exist_ok=True)
    (connection.image_dir / "latest_crop.jpg").write_bytes(b"the-crop-that-was-corrected")
    calibration = _calibration()

    correction_listener.apply_correction(connection, 214808.5, now=NOW, calibration=calibration)

    examples_dir = connection.image_dir / "human_corrections"
    index = json.loads((examples_dir / "index.json").read_text())
    assert len(index) == 1
    assert index[0]["digits"] == "02148085"
    saved_image = examples_dir / index[0]["file"]
    assert saved_image.read_bytes() == b"the-crop-that-was-corrected"


def test_apply_correction_without_calibration_does_not_save_a_dynamic_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    connection.image_dir.mkdir(parents=True, exist_ok=True)
    (connection.image_dir / "latest_crop.jpg").write_bytes(b"some-crop")

    correction_listener.apply_correction(connection, 214808.5, now=NOW)

    assert not (connection.image_dir / "human_corrections").exists()


def test_dynamic_examples_are_capped_at_the_configured_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_paho(monkeypatch)
    monkeypatch.setattr(correction_listener, "DYNAMIC_EXAMPLES_LIMIT", 2)
    connection = _connection(tmp_path)
    connection.image_dir.mkdir(parents=True, exist_ok=True)
    calibration = _calibration()

    for i in range(3):
        (connection.image_dir / "latest_crop.jpg").write_bytes(f"crop-{i}".encode())
        correction_listener.apply_correction(
            connection, 100.0 + i, now=NOW + timedelta(minutes=i), calibration=calibration
        )

    examples_dir = connection.image_dir / "human_corrections"
    index = json.loads((examples_dir / "index.json").read_text())
    assert len(index) == 2
    remaining_files = {p.name for p in examples_dir.glob("*.jpg")}
    assert remaining_files == {entry["file"] for entry in index}
