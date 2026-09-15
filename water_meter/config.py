from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_LIGHT_WARMUP_SECONDS = 1.5
DEFAULT_FRAMES_TO_DISCARD = 2
DEFAULT_FRAMES_TO_GRAB = 4
DEFAULT_HISTORY_LIMIT = 200
DEFAULT_MAX_GALLONS_PER_INTERVAL = 500.0
# Matches the systemd timer's OnUnitActiveSec (deploy/systemd/water-meter-
# reader.timer - 60min, raised from 10min on 2026-09-14 after the near-
# continuous vision-LLM load from a 10-minute cadence tripped the TrueNAS
# Ollama host's thermal alarm; see that file's comment). sanity.
# validate_reading scales max_gallons_per_interval by elapsed-time-since-
# last-good-reading / this value, so a run that's late (skipped/rejected
# polls, a watchdog reboot) gets a proportionally larger allowance instead
# of comparing accumulated usage against a limit sized for a single
# interval - see sanity.py for the incident that motivated this. Keep this
# in sync with the timer: if it drifts, the implausible-jump/stuck-detection
# windows silently stop meaning real wall-clock hours.
DEFAULT_NOMINAL_INTERVAL_SECONDS = 3600.0
DEFAULT_STUCK_AFTER_HOURS = 24.0
# 204/254 (~80%): bench-tested against the real jig. 100% blows out the LCD
# with direct glare (unreadable); 60-80% both read cleanly, so 80% gives the
# most margin before ambient light changes push it back into glare.
DEFAULT_LIGHT_BRIGHTNESS = 204
# The V4L2/GStreamer backend for this webcam has been observed to wedge
# (select() timeout on every read, even from a freshly opened
# cv2.VideoCapture in a brand-new process) in a way that only a host reboot
# clears - see water_meter/watchdog.py. Two consecutive capture failures
# (~20 minutes apart on the default 10-minute timer) is treated as "genuinely
# stuck" rather than a one-off USB hiccup, since every fresh-process retry
# during bench testing failed identically once wedged.
DEFAULT_CAPTURE_FAILURE_REBOOT_THRESHOLD = 2

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class ConnectionConfig:
    """Everything needed to reach the MQTT broker and the Zigbee light.

    Sourced from the environment (systemd Environment= lines), matching the
    inky_display service convention, since these are secrets/deployment
    details rather than meter-specific calibration data.
    """

    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    light_topic: str
    reading_topic: str
    last_reading_time_topic: str
    status_topic: str
    discovery_topic: str
    camera_device: str
    calibration_path: Path
    templates_dir: Path
    state_dir: Path
    image_dir: Path
    # Defaulted (unlike the fields above) so existing ConnectionConfig(...)
    # call sites - direct construction in tests, mainly - don't need updating
    # every time a new deployment knob is added here.
    light_brightness: int = DEFAULT_LIGHT_BRIGHTNESS
    capture_failure_reboot_threshold: int = DEFAULT_CAPTURE_FAILURE_REBOOT_THRESHOLD
    # Empty string (the default) disables the vision-LLM fallback tier
    # entirely - ocr.read_digits only tries it when vlm_host is truthy, so
    # deployments without an Ollama host keep the old ssocr-then-template
    # behavior unchanged. See ocr.py's read_digits_vlm/DEFAULT_VLM_TIMEOUT
    # for why the timeout default is so much larger than a typical HTTP call.
    vlm_host: str = ""
    vlm_model: str = "qwen3-vl:4b"
    vlm_timeout_seconds: float = 480.0


def connection_config_from_env() -> ConnectionConfig:
    return ConnectionConfig(
        mqtt_host=os.environ.get("WATER_METER_MQTT_HOST", "localhost"),
        mqtt_port=int(os.environ.get("WATER_METER_MQTT_PORT", "1883")),
        mqtt_username=os.environ.get("WATER_METER_MQTT_USERNAME", ""),
        mqtt_password=os.environ.get("WATER_METER_MQTT_PASSWORD", ""),
        light_topic=os.environ.get(
            "WATER_METER_LIGHT_TOPIC", "zigbee2mqtt/water_meter_flash/set"
        ),
        light_brightness=int(
            os.environ.get("WATER_METER_LIGHT_BRIGHTNESS", str(DEFAULT_LIGHT_BRIGHTNESS))
        ),
        reading_topic=os.environ.get(
            "WATER_METER_READING_TOPIC", "waterreader/sensor/water_meter/state"
        ),
        last_reading_time_topic=os.environ.get(
            "WATER_METER_LAST_READING_TIME_TOPIC",
            "waterreader/sensor/water_meter/last_reading_time",
        ),
        status_topic=os.environ.get(
            "WATER_METER_STATUS_TOPIC", "waterreader/sensor/water_meter/status"
        ),
        discovery_topic=os.environ.get(
            "WATER_METER_DISCOVERY_TOPIC", "homeassistant/sensor/water_meter/config"
        ),
        camera_device=os.environ.get(
            "WATER_METER_CAMERA_DEVICE", "/dev/v4l/by-id/water-meter-camera"
        ),
        calibration_path=Path(
            os.environ.get("WATER_METER_CALIBRATION_PATH", "/opt/water-meter/calibration.json")
        ),
        templates_dir=Path(
            os.environ.get("WATER_METER_TEMPLATES_DIR", "/opt/water-meter/digit_templates")
        ),
        state_dir=Path(os.environ.get("WATER_METER_STATE_DIR", "/var/lib/water-meter/state")),
        image_dir=Path(os.environ.get("WATER_METER_IMAGE_DIR", "/var/lib/water-meter/images")),
        capture_failure_reboot_threshold=int(
            os.environ.get(
                "WATER_METER_CAPTURE_FAILURE_REBOOT_THRESHOLD",
                str(DEFAULT_CAPTURE_FAILURE_REBOOT_THRESHOLD),
            )
        ),
        vlm_host=os.environ.get("WATER_METER_VLM_HOST", ""),
        vlm_model=os.environ.get("WATER_METER_VLM_MODEL", "qwen3-vl:4b"),
        vlm_timeout_seconds=float(
            os.environ.get("WATER_METER_VLM_TIMEOUT_SECONDS", "480.0")
        ),
    )


@dataclass(frozen=True)
class CalibrationConfig:
    """Meter-specific geometry and thresholds produced by calibrate.py.

    Kept separate from ConnectionConfig because this is structured data a
    human generates once by drawing boxes on a reference photo, not a scalar
    deployment secret - a small JSON file is a far better fit than env vars
    (and keeps this module dependency-free: stdlib json, no PyYAML).
    """

    roi: Box
    digit_boxes: tuple[Box, ...]
    digit_count: int
    excluded_digit_indexes: tuple[int, ...]
    warmup_seconds: float
    frames_to_grab: int
    frames_to_discard: int
    max_gallons_per_interval: float
    stuck_after_hours: float
    history_limit: int
    ssocr_args: tuple[str, ...]
    # The last N OCR'd digits are fractional - confirmed against real
    # captures of this meter, whose display has a fixed decimal point before
    # its final digit (raw read "02138978" is actually 213897.8 gallons).
    # Defaults to 0 (whole-number reading) for a meter with no decimal point.
    decimal_places: int = 0
    # Positions where template-match confidence gating is skipped - trust
    # match_digit's pick outright, even while the template set is
    # incomplete. Meant for digits under a fixed glare streak: real captures
    # show even a correctly-labeled template scoring barely higher than a
    # wrong one there (0.31 vs 0.31), so no confidence floor can separate
    # them, but these are also the highest-place-value digits (each only
    # advances once per 100,000+ gallons) - a wrong guess is either right or
    # produces a jump the sanity checks (max_gallons_per_interval) already
    # reject, so the confidence gate protects nothing here and only blocks
    # every other, genuinely reliable digit from ever being accepted.
    low_confidence_ok_indexes: tuple[int, ...] = ()
    # See DEFAULT_NOMINAL_INTERVAL_SECONDS - must match the deployed timer's
    # OnUnitActiveSec for the elapsed-interval scaling in
    # sanity.validate_reading to mean what its name says.
    nominal_interval_seconds: float = DEFAULT_NOMINAL_INTERVAL_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "roi": list(self.roi),
            "digit_boxes": [list(box) for box in self.digit_boxes],
            "digit_count": self.digit_count,
            "excluded_digit_indexes": list(self.excluded_digit_indexes),
            "warmup_seconds": self.warmup_seconds,
            "frames_to_grab": self.frames_to_grab,
            "frames_to_discard": self.frames_to_discard,
            "max_gallons_per_interval": self.max_gallons_per_interval,
            "stuck_after_hours": self.stuck_after_hours,
            "history_limit": self.history_limit,
            "ssocr_args": list(self.ssocr_args),
            "decimal_places": self.decimal_places,
            "low_confidence_ok_indexes": list(self.low_confidence_ok_indexes),
            "nominal_interval_seconds": self.nominal_interval_seconds,
        }


def calibration_config_from_dict(data: dict[str, Any]) -> CalibrationConfig:
    roi = data.get("roi")
    digit_boxes = data.get("digit_boxes", [])
    if roi is None or len(roi) != 4:
        raise ValueError("Calibration data must define a 4-element 'roi' box")

    return CalibrationConfig(
        roi=tuple(int(v) for v in roi),  # type: ignore[return-value]
        digit_boxes=tuple(tuple(int(v) for v in box) for box in digit_boxes),  # type: ignore[misc]
        digit_count=int(data.get("digit_count", len(digit_boxes))),
        excluded_digit_indexes=tuple(int(v) for v in data.get("excluded_digit_indexes", [])),
        warmup_seconds=float(data.get("warmup_seconds", DEFAULT_LIGHT_WARMUP_SECONDS)),
        frames_to_grab=int(data.get("frames_to_grab", DEFAULT_FRAMES_TO_GRAB)),
        frames_to_discard=int(data.get("frames_to_discard", DEFAULT_FRAMES_TO_DISCARD)),
        max_gallons_per_interval=float(
            data.get("max_gallons_per_interval", DEFAULT_MAX_GALLONS_PER_INTERVAL)
        ),
        stuck_after_hours=float(data.get("stuck_after_hours", DEFAULT_STUCK_AFTER_HOURS)),
        history_limit=int(data.get("history_limit", DEFAULT_HISTORY_LIMIT)),
        ssocr_args=tuple(str(v) for v in data.get("ssocr_args", [])),
        decimal_places=int(data.get("decimal_places", 0)),
        low_confidence_ok_indexes=tuple(
            int(v) for v in data.get("low_confidence_ok_indexes", [])
        ),
        nominal_interval_seconds=float(
            data.get("nominal_interval_seconds", DEFAULT_NOMINAL_INTERVAL_SECONDS)
        ),
    )


def load_calibration_config(path: Path) -> CalibrationConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Calibration file {path} must contain a JSON object")
    return calibration_config_from_dict(data)


def save_calibration_config(path: Path, config: CalibrationConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=False), encoding="utf-8")
