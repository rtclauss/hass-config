from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Callable, TYPE_CHECKING

from . import capture, ocr, sanity, watchdog
from .config import (
    CalibrationConfig,
    ConnectionConfig,
    connection_config_from_env,
    load_calibration_config,
)

if TYPE_CHECKING:
    import numpy as np

LOG = logging.getLogger(__name__)

GrabFrame = Callable[[], "np.ndarray"]
SetLight = Callable[[bool], None]
OcrReader = Callable[..., str]
Publisher = Callable[["RunResult", datetime], None]
Reboot = Callable[[], None]


@dataclass(frozen=True)
class RunResult:
    accepted: bool
    value: float | None
    reason: str
    stuck: bool = False


def run_once(
    connection: ConnectionConfig,
    calibration: CalibrationConfig,
    *,
    grab_frame: GrabFrame | None = None,
    set_light: SetLight | None = None,
    ocr_reader: OcrReader | None = None,
    publisher: Publisher | None = None,
    reboot: Reboot | None = None,
    now: datetime | None = None,
) -> RunResult:
    """Light on -> capture -> light off -> crop -> OCR -> validate -> publish.

    Every dependency is injectable so the orchestration logic here can be
    unit tested with fakes instead of a real camera, MQTT broker, or ssocr
    binary - only the default implementations below touch real hardware.
    """
    grab_frame = grab_frame or (
        lambda: capture.grab_stable_frame(
            connection.camera_device,
            frames_to_grab=calibration.frames_to_grab,
            frames_to_discard=calibration.frames_to_discard,
        )
    )
    set_light = set_light or (lambda on: capture.set_light(connection, on=on))
    publisher = publisher or default_publisher(connection)
    reboot = reboot or watchdog.trigger_reboot
    now = now or datetime.now(timezone.utc)

    last_good = sanity.load_last_good(connection.state_dir)
    ocr_reader = ocr_reader or (
        lambda image_path, digit_crops: ocr.read_digits(
            image_path,
            digit_crops,
            calibration,
            templates_dir=connection.templates_dir,
            bootstrap=last_good is None,
            vlm_host=connection.vlm_host or None,
            vlm_model=connection.vlm_model,
            vlm_timeout=connection.vlm_timeout_seconds,
        )
    )

    set_light(True)
    try:
        time.sleep(calibration.warmup_seconds)
        frame = grab_frame()
    except capture.CaptureError as error:
        return _handle_capture_failure(connection, error, publisher, reboot, now)
    finally:
        set_light(False)

    watchdog.record_capture_success(connection.state_dir)

    raw_path = connection.image_dir / "latest_raw.jpg"
    crop_path = connection.image_dir / "latest_crop.jpg"
    capture.save_image(frame, raw_path)

    cropped = capture.crop_roi(frame, calibration.roi)
    capture.save_image(cropped, crop_path)
    digit_crops = capture.crop_boxes(frame, calibration.digit_boxes)

    _rotate_history(
        connection.image_dir / "history", frame, cropped, digit_crops, calibration.history_limit, now
    )

    try:
        raw_digits = ocr_reader(crop_path, digit_crops)
    except ocr.OcrError as error:
        result = RunResult(False, None, f"ocr failed: {error}")
        _save_reject(connection.image_dir / "rejects", cropped, result.reason, now)
        publisher(result, now)
        return result

    validation = sanity.validate_reading(
        raw_digits,
        digit_count=calibration.digit_count,
        max_gallons_per_interval=calibration.max_gallons_per_interval,
        last_good=last_good,
        now=now,
        history_limit=calibration.history_limit,
        decimal_places=calibration.decimal_places,
        nominal_interval_seconds=calibration.nominal_interval_seconds,
    )

    if not validation.accepted and connection.vlm_host and last_good is not None:
        raw_digits, validation = _requery_vlm_on_suspect_value(
            connection, calibration, crop_path, raw_digits, validation, last_good, now
        )

    if not validation.accepted:
        result = RunResult(False, None, validation.reason)
        _save_reject(connection.image_dir / "rejects", cropped, result.reason, now)
        publisher(result, now)
        return result

    new_last_good = sanity.next_last_good(
        validation.value, last_good, history_limit=calibration.history_limit, now=now
    )
    sanity.save_last_good(connection.state_dir, new_last_good)

    reason = "stuck: unchanged for the full history window" if validation.stuck else "ok"
    result = RunResult(True, validation.value, reason, stuck=validation.stuck)
    publisher(result, now)
    return result


def default_publisher(connection: ConnectionConfig) -> Publisher:
    def publish(result: RunResult, now: datetime) -> None:
        from paho.mqtt import publish as mqtt_publish

        # A stuck reading is still `accepted` (the value itself is legitimate
        # and unchanged - see sanity.validate_reading's `stuck` flag), but
        # publishing "ok" here would make a frozen camera/OCR pipeline look
        # perfectly healthy forever: packages/water_meter.yaml's staleness
        # automation only alerts on reading_age or a status starting with
        # "error", and last_reading_time keeps advancing on every accepted
        # run (stuck or not), so reading_age never grows either. Reusing the
        # existing "error:" prefix for a stuck status is what actually makes
        # the advertised stuck-reading detection reach that automation.
        healthy = result.accepted and not result.stuck
        messages = [
            {
                "topic": connection.status_topic,
                "payload": "ok" if healthy else f"error:{result.reason}",
                "retain": True,
            },
            {
                "topic": connection.discovery_topic,
                "payload": json.dumps(discovery_payload(connection)),
                "retain": True,
            },
        ]
        if result.accepted:
            messages.append(
                {"topic": connection.reading_topic, "payload": str(result.value), "retain": True}
            )
            messages.append(
                {
                    "topic": connection.last_reading_time_topic,
                    "payload": now.isoformat(),
                    "retain": True,
                }
            )

        capture.publish_with_retry(
            lambda: mqtt_publish.multiple(
                messages,
                hostname=connection.mqtt_host,
                port=connection.mqtt_port,
                auth=capture.mqtt_auth(connection),
            )
        )

    return publish


def noop_publisher(result: RunResult, now: datetime) -> None:
    LOG.info("Dry run - not publishing. accepted=%s value=%s reason=%s", result.accepted, result.value, result.reason)


def discovery_payload(connection: ConnectionConfig) -> dict:
    """MQTT discovery config for sensor.water_meter.

    device/origin are what actually make this show up properly in HA's
    device registry and MQTT integration page (grouped device, not an
    orphan entity) rather than cosmetic extras - confirmed against the
    current MQTT discovery docs. No icon needed: device_class "water"
    already gives the frontend a water-drop icon automatically.
    """
    return {
        "name": "Water Meter",
        "unique_id": "water_meter",
        "state_topic": connection.reading_topic,
        "availability_topic": connection.status_topic,
        "payload_available": "ok",
        "device_class": "water",
        "state_class": "total_increasing",
        "unit_of_measurement": "gal",
        "device": {
            "identifiers": ["water_meter_reader"],
            "name": "Water Meter Reader",
            "manufacturer": "Home-built (Raspberry Pi + webcam OCR)",
            "model": 'Mueller Systems 3/4" S encoder register',
        },
        "origin": {
            "name": "water-meter-reader",
        },
    }


def _handle_capture_failure(
    connection: ConnectionConfig,
    error: capture.CaptureError,
    publisher: Publisher,
    reboot: Reboot,
    now: datetime,
) -> RunResult:
    """Track consecutive capture failures and reboot once they cross the threshold.

    The V4L2/GStreamer backend for the bench-tested webcam has been observed
    to wedge - every read times out, even from a freshly opened
    cv2.VideoCapture in a brand-new process - in a way that only a host
    reboot clears. Since each run is already a fresh process (the systemd
    timer), a single failure could still be a one-off USB hiccup, so this
    only escalates to a reboot after connection.capture_failure_reboot_threshold
    consecutive failures; a single successful capture (see the call to
    watchdog.record_capture_success above) resets the count.
    """
    streak = watchdog.record_capture_failure(connection.state_dir)
    reason = f"capture failed (streak {streak}): {error}"
    LOG.error(reason)
    publisher(RunResult(False, None, reason), now)

    if watchdog.should_reboot(streak, threshold=connection.capture_failure_reboot_threshold):
        reboot_reason = f"camera stuck after {streak} consecutive failures, rebooting"
        LOG.error(reboot_reason)
        publisher(RunResult(False, None, reboot_reason), now)
        watchdog.record_capture_success(connection.state_dir)  # fresh count after reboot
        reboot()
        return RunResult(False, None, reboot_reason)

    return RunResult(False, None, reason)


def _requery_vlm_on_suspect_value(
    connection: ConnectionConfig,
    calibration: CalibrationConfig,
    crop_path: Path,
    raw_digits: str,
    validation: "sanity.ValidationResult",
    last_good: "sanity.LastGoodReading",
    now: datetime,
) -> tuple[str, "sanity.ValidationResult"]:
    """Give the vision LLM one more look at the same crop before giving up.

    "value decreased" and "implausible jump" mean digits were parsed fine
    but the resulting value looks wrong - the signature of a single misread
    digit (confirmed live: qwen3-vl itself occasionally flips the
    glare-affected leading digit, see ocr.read_digits_vlm) rather than a
    garbled read that no amount of re-asking would fix. The meter hasn't
    moved between the first attempt and now, so requerying the same crop -
    with the suspicious value and the last confirmed reading as context -
    gives the model a second, better-informed chance instead of discarding
    a capture that was probably one digit away from correct. Fires at most
    once (no loop) and only for these two reasons; every other rejection
    (bad digit count, non-numeric, ocr failed outright) means there's
    nothing a requery on the same image would fix.
    """
    if not (validation.reason.startswith("value decreased") or validation.reason.startswith("implausible jump")):
        return raw_digits, validation

    LOG.info("First read rejected (%s); requerying the vision-LLM for a second look", validation.reason)
    hint = (
        f"A first read of this exact image gave {raw_digits}, which would be "
        f"{validation.reason} versus the last confirmed reading of {last_good.value}. "
        "That is more likely a misread of one digit than a real jump - look very "
        "carefully at each digit, especially the leftmost ones which are sometimes "
        "affected by glare, and answer again with exactly the digits you see."
    )
    try:
        requery_digits = ocr.read_digits_vlm(
            crop_path,
            host=connection.vlm_host,
            digit_count=calibration.digit_count,
            model=connection.vlm_model,
            timeout=connection.vlm_timeout_seconds,
            hint=hint,
        )
    except ocr.OcrError as error:
        LOG.warning("Vision-LLM requery failed (%s); keeping the original rejection", error)
        return raw_digits, validation

    requery_validation = sanity.validate_reading(
        requery_digits,
        digit_count=calibration.digit_count,
        max_gallons_per_interval=calibration.max_gallons_per_interval,
        last_good=last_good,
        now=now,
        history_limit=calibration.history_limit,
        decimal_places=calibration.decimal_places,
        nominal_interval_seconds=calibration.nominal_interval_seconds,
    )
    if requery_validation.accepted:
        LOG.info("Vision-LLM requery succeeded: %s -> %s", raw_digits, requery_digits)
    else:
        LOG.info("Vision-LLM requery also rejected (%s)", requery_validation.reason)
    return requery_digits, requery_validation


def _rotate_history(
    history_dir: Path,
    frame: "np.ndarray",
    cropped: "np.ndarray",
    digit_crops: list["np.ndarray"],
    limit: int,
    now: datetime,
) -> None:
    """Save this run's raw frame, ROI crop, and individual digit slices.

    Digit slices are saved on every run - accepted, rejected, or OCR-failed -
    not just failures: building a broad, real-world sample library (not only
    the cases that happened to fail) is what let calibration drift and
    missing digit templates (see ocr.py's completeness check) get fixed from
    actual captures instead of guesswork. Sharing history_dir's existing
    stamp-based rotation keeps this bounded automatically.
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    capture.save_image(frame, history_dir / f"{stamp}_raw.jpg")
    capture.save_image(cropped, history_dir / f"{stamp}_crop.jpg")
    for index, digit_crop in enumerate(digit_crops):
        capture.save_image(digit_crop, history_dir / f"{stamp}_digit{index}.jpg")

    existing_pairs = sorted({path.name.split("_", 1)[0] for path in history_dir.glob("*.jpg")})
    for stale_stamp in existing_pairs[:-limit] if limit > 0 else []:
        for stale in history_dir.glob(f"{stale_stamp}_*.jpg"):
            stale.unlink(missing_ok=True)


def _save_reject(rejects_dir: Path, cropped: "np.ndarray", reason: str, now: datetime) -> None:
    rejects_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)[:80]
    capture.save_image(cropped, rejects_dir / f"{stamp}_{safe_reason}.jpg")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture and OCR a water meter reading, then publish it to MQTT."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full capture/OCR/validation pipeline but do not publish to MQTT.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Load configuration and exit without touching the camera, light, or MQTT.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=os.environ.get("WATER_METER_LOG_LEVEL", "INFO"))
    connection = connection_config_from_env()
    calibration = load_calibration_config(connection.calibration_path)

    if args.check_config:
        LOG.info(
            "Loaded water meter config: camera=%s roi=%s digits=%s",
            connection.camera_device,
            calibration.roi,
            calibration.digit_count,
        )
        return

    publisher = noop_publisher if args.dry_run else None
    result = run_once(connection, calibration, publisher=publisher)
    LOG.info(
        "Run result: accepted=%s value=%s reason=%s", result.accepted, result.value, result.reason
    )
    raise SystemExit(0 if result.accepted else 1)


if __name__ == "__main__":
    main()
