from __future__ import annotations

from pathlib import Path

from water_meter import capture
from water_meter.config import ConnectionConfig


class FakeFrame:
    """Minimal stand-in for a numpy ndarray supporting frame[y:y+h, x:x+w].

    Real image arrays aren't available in this test environment (no numpy),
    but crop_roi/crop_boxes only rely on 2D tuple-slice indexing, which is
    easy to fake and worth testing directly - ROI off-by-one errors are
    exactly the kind of silent-garbage-reading bug this project exists to
    avoid.
    """

    def __init__(self, rows: list[list[int]]) -> None:
        self.rows = rows

    def __getitem__(self, key: tuple[slice, slice]) -> "FakeFrame":
        row_slice, col_slice = key
        return FakeFrame([row[col_slice] for row in self.rows[row_slice]])

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeFrame) and self.rows == other.rows

    def __repr__(self) -> str:
        return f"FakeFrame({self.rows!r})"


def _grid(width: int, height: int) -> FakeFrame:
    return FakeFrame([[y * width + x for x in range(width)] for y in range(height)])


def test_crop_roi_extracts_expected_pixel_window() -> None:
    frame = _grid(width=10, height=10)

    cropped = capture.crop_roi(frame, (2, 3, 4, 2))

    assert cropped == FakeFrame([[32, 33, 34, 35], [42, 43, 44, 45]])


def test_crop_boxes_returns_one_crop_per_box_in_order() -> None:
    frame = _grid(width=10, height=1)

    crops = capture.crop_boxes(frame, ((0, 0, 2, 1), (5, 0, 3, 1)))

    assert crops == [FakeFrame([[0, 1]]), FakeFrame([[5, 6, 7]])]


def _connection(**overrides: object) -> ConnectionConfig:
    defaults: dict[str, object] = dict(
        mqtt_host="broker",
        mqtt_port=1883,
        mqtt_username="",
        mqtt_password="",
        light_topic="zigbee2mqtt/light/set",
        reading_topic="t/state",
        last_reading_time_topic="t/last",
        status_topic="t/status",
        discovery_topic="homeassistant/sensor/water_meter/config",
        camera_device="/dev/fake",
        calibration_path=Path("/tmp/calibration.json"),
        templates_dir=Path("/tmp/templates"),
        state_dir=Path("/tmp/state"),
        image_dir=Path("/tmp/images"),
    )
    defaults.update(overrides)
    return ConnectionConfig(**defaults)  # type: ignore[arg-type]


def test_mqtt_auth_is_none_without_a_username() -> None:
    assert capture.mqtt_auth(_connection()) is None


def test_mqtt_auth_includes_credentials_when_username_set() -> None:
    connection = _connection(mqtt_username="z2muser", mqtt_password="secret")

    assert capture.mqtt_auth(connection) == {"username": "z2muser", "password": "secret"}


def test_publish_with_retry_succeeds_without_retrying_on_first_try() -> None:
    calls: list[int] = []

    capture.publish_with_retry(lambda: calls.append(1), backoff_seconds=0)

    assert calls == [1]


def test_publish_with_retry_recovers_from_a_transient_failure(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: sleeps.append(seconds))
    attempts: list[int] = []

    def flaky() -> None:
        attempts.append(1)
        if len(attempts) < 2:
            raise TimeoutError("timed out")

    capture.publish_with_retry(flaky, attempts=3, backoff_seconds=2.0)

    assert len(attempts) == 2
    assert sleeps == [2.0]


def test_publish_with_retry_raises_the_last_error_after_exhausting_attempts(monkeypatch) -> None:
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: None)

    def always_fails() -> None:
        raise OSError("still down")

    try:
        capture.publish_with_retry(always_fails, attempts=3, backoff_seconds=0)
        assert False, "expected OSError to propagate"
    except OSError as error:
        assert "still down" in str(error)
