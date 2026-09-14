from __future__ import annotations

import json
import logging
import time
from typing import Callable, TYPE_CHECKING

from .config import Box, ConnectionConfig

if TYPE_CHECKING:
    import numpy as np


LOG = logging.getLogger(__name__)


class CaptureError(RuntimeError):
    """Raised when the webcam cannot produce a usable frame."""


def publish_with_retry(
    publish_call: Callable[[], None], *, attempts: int = 3, backoff_seconds: float = 2.0
) -> None:
    """Retry an MQTT publish a few times before giving up.

    The Pi reaches the broker over WiFi (observed directly: a bare TCP
    connect to the broker timed out once, then succeeded on the very next
    attempt seconds later). A single transient link hiccup shouldn't throw
    away a capture+OCR run that otherwise succeeded, or force a wait for the
    next ~10-minute timer tick to try again.
    """
    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            publish_call()
            return
        except OSError as error:
            last_error = error
            LOG.warning("MQTT publish attempt %d/%d failed: %s", attempt, attempts, error)
            if attempt < attempts:
                time.sleep(backoff_seconds)
    assert last_error is not None
    raise last_error


def set_light(connection: ConnectionConfig, *, on: bool) -> None:
    """Publish directly to the zigbee2mqtt light topic.

    Talking straight to the broker (the same one Zigbee2MQTT uses) rather
    than routing through Home Assistant means the capture loop has one fewer
    dependency: it keeps working even if HA itself is down.

    Brightness is only meaningful (and only sent) when turning the light on:
    bench testing against the real jig found 100% brightness glares off the
    meter's LCD badly enough to blow out the digits entirely, while 60-80%
    both read cleanly - connection.light_brightness defaults to 80% with
    margin either side. This bulb (Hue White A19) has no color_temp support,
    so brightness is the only tunable here.
    """
    from paho.mqtt import publish

    payload_data: dict[str, object] = {"state": "ON" if on else "OFF"}
    if on:
        payload_data["brightness"] = connection.light_brightness
    payload = json.dumps(payload_data)
    auth = mqtt_auth(connection)
    publish_with_retry(
        lambda: publish.single(
            connection.light_topic,
            payload=payload,
            hostname=connection.mqtt_host,
            port=connection.mqtt_port,
            auth=auth,
        )
    )
    LOG.info("Published light %s to %s", "ON" if on else "OFF", connection.light_topic)


def grab_stable_frame(device: str, *, frames_to_grab: int, frames_to_discard: int) -> "np.ndarray":
    """Open the webcam, discard the auto-exposure settling frames, return the last."""
    import cv2

    capture = cv2.VideoCapture(device)
    if not capture.isOpened():
        raise CaptureError(f"Could not open camera device {device!r}")

    try:
        frame = None
        for index in range(max(frames_to_grab, frames_to_discard + 1)):
            ok, candidate = capture.read()
            if not ok:
                raise CaptureError(f"Failed to read frame {index} from {device!r}")
            if index >= frames_to_discard:
                frame = candidate
        if frame is None:
            raise CaptureError(f"No frames captured from {device!r}")
        return frame
    finally:
        capture.release()


def crop_roi(frame: "np.ndarray", roi: Box) -> "np.ndarray":
    x, y, width, height = roi
    return frame[y : y + height, x : x + width]


def crop_boxes(frame: "np.ndarray", boxes: tuple[Box, ...]) -> list["np.ndarray"]:
    return [crop_roi(frame, box) for box in boxes]


def save_image(frame: "np.ndarray", path) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise CaptureError(f"Failed to write image to {path}")


def mqtt_auth(connection: ConnectionConfig) -> dict[str, str] | None:
    if not connection.mqtt_username:
        return None
    return {"username": connection.mqtt_username, "password": connection.mqtt_password}
