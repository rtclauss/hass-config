from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import types

import pytest

from water_meter import capture, ocr, reader, sanity, watchdog
from water_meter.config import CalibrationConfig, ConnectionConfig


def _install_fake_paho(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stand in for paho-mqtt, which isn't installed in the test environment
    (see the module docstring on _stub_image_io for the same reasoning re:
    cv2/numpy). Returns the list default_publisher's messages get appended
    to, so a test can assert on exactly what would have gone to MQTT.
    """
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


NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _connection(tmp_path: Path, **overrides: object) -> ConnectionConfig:
    defaults: dict[str, object] = dict(
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
    defaults.update(overrides)
    return ConnectionConfig(**defaults)  # type: ignore[arg-type]


def _calibration(**overrides: object) -> CalibrationConfig:
    defaults = dict(
        roi=(0, 0, 10, 10),
        digit_boxes=((0, 0, 5, 5), (5, 0, 5, 5)),
        digit_count=2,
        excluded_digit_indexes=(),
        warmup_seconds=0.0,
        frames_to_grab=1,
        frames_to_discard=0,
        max_gallons_per_interval=500.0,
        stuck_after_hours=24.0,
        history_limit=5,
        ssocr_args=(),
    )
    defaults.update(overrides)
    return CalibrationConfig(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _stub_image_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for capture's cv2/numpy-backed image I/O.

    cv2 and numpy aren't installed in the test environment (this repo's CI
    runs `uv run --with pytest pytest` - pytest only), matching how
    inky_display keeps hardware libraries out of anything pytest imports at
    collection time. These tests exercise run_once's orchestration logic
    (light sequencing, validation gating, publish calls), not image math.
    """
    monkeypatch.setattr(capture, "save_image", lambda frame, path: None)
    monkeypatch.setattr(capture, "crop_roi", lambda frame, roi: frame)
    monkeypatch.setattr(capture, "crop_boxes", lambda frame, boxes: [frame] * len(boxes))


def test_accepted_run_toggles_light_and_publishes_reading(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    light_calls: list[bool] = []
    published: list[tuple[reader.RunResult, datetime]] = []

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=light_calls.append,
        ocr_reader=lambda image_path, digit_crops: "12",
        publisher=lambda res, now: published.append((res, now)),
        now=NOW,
    )

    assert light_calls == [True, False]
    assert result == reader.RunResult(True, 12.0, "ok", stuck=False)
    assert published == [(result, NOW)]

    last_good = sanity.load_last_good(connection.state_dir)
    assert last_good is not None
    assert last_good.value == 12.0


def _boom() -> None:
    raise capture.CaptureError("camera unplugged")


def test_light_is_turned_off_even_if_capture_fails(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    light_calls: list[bool] = []

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=_boom,
        set_light=light_calls.append,
        publisher=lambda res, now: None,
        reboot=lambda: None,
        now=NOW,
    )

    assert light_calls == [True, False]
    # A capture failure is tracked, not raised - see the watchdog tests below
    # for the escalate-to-reboot behavior this enables.
    assert result.accepted is False
    assert "capture failed" in result.reason


def test_capture_failure_below_threshold_does_not_reboot(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    assert connection.capture_failure_reboot_threshold >= 2  # otherwise this test proves nothing
    reboots: list[None] = []

    reader.run_once(
        connection,
        calibration,
        grab_frame=_boom,
        set_light=lambda on: None,
        publisher=lambda res, now: None,
        reboot=lambda: reboots.append(None),
        now=NOW,
    )

    assert reboots == []
    assert watchdog.load_failure_streak(connection.state_dir) == 1


def test_capture_failure_at_threshold_reboots_and_resets_streak(tmp_path: Path) -> None:
    connection = _connection(tmp_path, capture_failure_reboot_threshold=2)
    calibration = _calibration()
    reboots: list[None] = []
    published: list[reader.RunResult] = []

    # First failure: below threshold, no reboot yet.
    reader.run_once(
        connection,
        calibration,
        grab_frame=_boom,
        set_light=lambda on: None,
        publisher=lambda res, now: published.append(res),
        reboot=lambda: reboots.append(None),
        now=NOW,
    )
    assert reboots == []

    # Second consecutive failure: crosses the threshold.
    result = reader.run_once(
        connection,
        calibration,
        grab_frame=_boom,
        set_light=lambda on: None,
        publisher=lambda res, now: published.append(res),
        reboot=lambda: reboots.append(None),
        now=NOW,
    )

    assert reboots == [None]
    assert "rebooting" in result.reason
    # Reset after the reboot decision, so a fresh boot starts counting at
    # zero instead of immediately looking "already stuck" again.
    assert watchdog.load_failure_streak(connection.state_dir) == 0


def test_successful_capture_resets_a_prior_failure_streak(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    watchdog.record_capture_failure(connection.state_dir)
    assert watchdog.load_failure_streak(connection.state_dir) == 1

    reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "12",
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert watchdog.load_failure_streak(connection.state_dir) == 0


def test_ocr_failure_is_rejected_and_not_published_as_reading(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    published: list[reader.RunResult] = []

    def _fail_ocr(image_path: Path, digit_crops: list[object]) -> str:
        raise ocr.OcrError("ssocr not found")

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=_fail_ocr,
        publisher=lambda res, now: published.append(res),
        now=NOW,
    )

    assert result.accepted is False
    assert "ocr failed" in result.reason
    assert published == [result]
    assert sanity.load_last_good(connection.state_dir) is None


def test_decreasing_reading_is_rejected_and_last_good_untouched(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()

    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=99.0, timestamp=NOW.isoformat())
    )

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "12",
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result.accepted is False
    assert "decreased" in result.reason
    restored = sanity.load_last_good(connection.state_dir)
    assert restored is not None
    assert restored.value == 99.0


def test_wrong_digit_count_is_rejected_end_to_end(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration(digit_count=7)

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "12",
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result.accepted is False
    assert "digits" in result.reason


def test_default_ocr_reader_passes_bootstrap_true_with_no_prior_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    calls: list[dict] = []
    monkeypatch.setattr(
        ocr,
        "read_digits",
        lambda image_path, digit_crops, calibration, **kwargs: calls.append(kwargs) or "12",
    )

    reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert len(calls) == 1
    assert calls[0]["bootstrap"] is True


def test_default_ocr_reader_passes_bootstrap_false_once_a_reading_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        ocr,
        "read_digits",
        lambda image_path, digit_crops, calibration, **kwargs: calls.append(kwargs) or "12",
    )

    reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert len(calls) == 1
    assert calls[0]["bootstrap"] is False


def test_default_ocr_reader_forwards_vlm_settings_from_connection_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(
        tmp_path,
        vlm_host="truenas.local:30068",
        vlm_model="qwen3-vl:4b",
        vlm_timeout_seconds=240.0,
    )
    calibration = _calibration()
    calls: list[dict] = []
    monkeypatch.setattr(
        ocr,
        "read_digits",
        lambda image_path, digit_crops, calibration, **kwargs: calls.append(kwargs) or "12",
    )

    reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert len(calls) == 1
    assert calls[0]["vlm_host"] == "truenas.local:30068"
    assert calls[0]["vlm_model"] == "qwen3-vl:4b"
    assert calls[0]["vlm_timeout"] == 240.0


def test_default_ocr_reader_passes_none_when_vlm_host_is_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path, vlm_host="")
    calibration = _calibration()
    calls: list[dict] = []
    monkeypatch.setattr(
        ocr,
        "read_digits",
        lambda image_path, digit_crops, calibration, **kwargs: calls.append(kwargs) or "12",
    )

    reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert len(calls) == 1
    assert calls[0]["vlm_host"] is None


def test_every_run_saves_a_digit_slice_per_box_into_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path)
    calibration = _calibration()  # two digit_boxes
    saved_paths: list[Path] = []
    monkeypatch.setattr(capture, "save_image", lambda frame, path: saved_paths.append(path))

    reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "12",
        publisher=lambda res, now: None,
        now=NOW,
    )

    history_names = {path.name for path in saved_paths if path.parent.name == "history"}
    stamp = NOW.strftime("%Y%m%dT%H%M%SZ")
    assert f"{stamp}_digit0.jpg" in history_names
    assert f"{stamp}_digit1.jpg" in history_names
    # Slices are saved regardless of whether OCR/validation ultimately
    # accepts the run - they're the raw material for fixing calibration
    # drift and building digit templates, not just a failure log.
    assert f"{stamp}_raw.jpg" in history_names
    assert f"{stamp}_crop.jpg" in history_names


def test_noop_publisher_does_not_raise() -> None:
    reader.noop_publisher(reader.RunResult(True, 5.0, "ok"), NOW)


def test_discovery_payload_matches_documented_mqtt_contract(tmp_path: Path) -> None:
    connection = _connection(tmp_path)

    payload = reader.discovery_payload(connection)

    assert payload["device_class"] == "water"
    assert payload["state_class"] == "total_increasing"
    assert payload["state_topic"] == connection.reading_topic
    assert payload["availability_topic"] == connection.status_topic
    assert payload["payload_available"] == "ok"

    # Confirmed against the current MQTT discovery docs: these are what
    # actually make the entity show up grouped under a real device (not an
    # orphan) in HA's device registry and MQTT integration page.
    assert payload["device"]["identifiers"] == ["water_meter_reader"]
    assert payload["device"]["name"]
    assert payload["origin"]["name"]


def test_implausible_jump_triggers_a_vlm_requery_that_can_rescue_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration(max_gallons_per_interval=5.0)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )
    requery_calls: list[dict] = []
    monkeypatch.setattr(
        ocr,
        "read_digits_vlm",
        lambda image_path, **kwargs: requery_calls.append(kwargs) or "11",
    )

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "99",  # +89, exceeds max_gallons_per_interval=5
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert len(requery_calls) == 1
    assert requery_calls[0]["digit_count"] == calibration.digit_count
    assert "99" in requery_calls[0]["hint"]
    assert "10.0" in requery_calls[0]["hint"]
    assert result == reader.RunResult(True, 11.0, "ok", stuck=False)


def test_requery_that_still_fails_validation_keeps_the_run_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration(max_gallons_per_interval=5.0)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda image_path, **kwargs: "98")  # still +88

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "99",
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result.accepted is False
    assert "implausible jump" in result.reason


def test_requery_error_keeps_the_original_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration(max_gallons_per_interval=5.0)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )

    def _fail(image_path: object, **kwargs: object) -> str:
        raise ocr.OcrError("vision-LLM request timed out")

    monkeypatch.setattr(ocr, "read_digits_vlm", _fail)

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "99",
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result.accepted is False
    assert "implausible jump" in result.reason


def test_requery_is_skipped_when_no_vlm_host_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path, vlm_host="")
    calibration = _calibration(max_gallons_per_interval=5.0)
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )

    def _unexpected(image_path: object, **kwargs: object) -> str:
        raise AssertionError("should not be called when vlm_host is unconfigured")

    monkeypatch.setattr(ocr, "read_digits_vlm", _unexpected)

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "99",
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result.accepted is False


def test_requery_is_skipped_for_rejection_reasons_a_second_look_cannot_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # digit_count mismatch, not a suspicious-value rejection - re-asking the
    # same question of the same image wouldn't change the digit count.
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration()
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )

    def _unexpected(image_path: object, **kwargs: object) -> str:
        raise AssertionError("should not be called for a digit-count mismatch")

    monkeypatch.setattr(ocr, "read_digits_vlm", _unexpected)

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "999",  # calibration expects 2 digits
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result.accepted is False
    assert "expected 2 digits" in result.reason


def test_implausible_jump_is_self_healed_from_last_good_before_any_vlm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Position 0 is the documented glare-affected digit - last_good's own
    # digit there ('1', from "10") is a better source of truth than a fresh
    # misread ('9'). The trailing digit genuinely changed (0 -> 1), so the
    # corrected candidate is a plausible +1 increase, not just a no-op.
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration(max_gallons_per_interval=5.0, low_confidence_ok_indexes=(0,))
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )

    def _unexpected(image_path: object, **kwargs: object) -> str:
        raise AssertionError("self-heal should have resolved this for free")

    monkeypatch.setattr(ocr, "read_digits_vlm", _unexpected)

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "91",  # true "11": +1, plausible
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result == reader.RunResult(True, 11.0, "ok", stuck=False)


def test_self_heal_is_skipped_when_no_glare_positions_are_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration(max_gallons_per_interval=5.0)  # low_confidence_ok_indexes=() default
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda image_path, **kwargs: "11")

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "91",
        publisher=lambda res, now: None,
        now=NOW,
    )

    # No glare positions configured -> self-heal can't apply -> falls through
    # to the VLM requery, which is what actually rescues it here.
    assert result == reader.RunResult(True, 11.0, "ok", stuck=False)


def test_self_heal_falls_through_to_vlm_requery_when_it_cannot_resolve_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The misread isn't at a glare position, so splicing in last_good's
    # digit there doesn't fix anything - must still fall through to the VLM.
    connection = _connection(tmp_path, vlm_host="truenas.local:30068")
    calibration = _calibration(max_gallons_per_interval=5.0, low_confidence_ok_indexes=(0,))
    sanity.save_last_good(
        connection.state_dir, sanity.LastGoodReading(value=10.0, timestamp=NOW.isoformat())
    )
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda image_path, **kwargs: "11")

    result = reader.run_once(
        connection,
        calibration,
        grab_frame=lambda: "frame",
        set_light=lambda on: None,
        ocr_reader=lambda image_path, digit_crops: "99",  # position 1 (not glare) is the bad digit
        publisher=lambda res, now: None,
        now=NOW,
    )

    assert result == reader.RunResult(True, 11.0, "ok", stuck=False)


def test_default_publisher_reports_error_status_for_a_stuck_reading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression test: a stuck reading is `accepted` (the value is real and
    # unchanged), but publishing "ok" would make a frozen camera/OCR
    # pipeline look perfectly healthy forever - packages/water_meter.yaml's
    # staleness automation only alerts on sensor.water_meter_reading_age or
    # a status starting with "error".
    published = _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    publisher = reader.default_publisher(connection)

    publisher(
        reader.RunResult(True, 12.0, "stuck: unchanged for the full history window", stuck=True),
        NOW,
    )

    status_message = next(m for m in published if m["topic"] == connection.status_topic)
    assert status_message["payload"] == "error:stuck: unchanged for the full history window"


def test_default_publisher_reports_ok_status_for_a_healthy_accepted_reading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    published = _install_fake_paho(monkeypatch)
    connection = _connection(tmp_path)
    publisher = reader.default_publisher(connection)

    publisher(reader.RunResult(True, 12.0, "ok", stuck=False), NOW)

    status_message = next(m for m in published if m["topic"] == connection.status_topic)
    assert status_message["payload"] == "ok"
    reading_message = next(m for m in published if m["topic"] == connection.reading_topic)
    assert reading_message["payload"] == "12.0"
