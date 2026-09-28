"""Persistent listener that applies a human's approved/corrected water meter
reading, sent from a Home Assistant automation reacting to the actionable
notification in reader.py's _notify_ha_of_unresolved_reading.

Deliberately a separate, always-on service (systemd Restart=always) rather
than folded into water_meter.reader: the reader is a one-shot systemd-timer
job that has already exited by the time a human responds to a notification
- minutes or hours later - so something has to stay up to receive that
response. See docs/water_meter.md "Human-in-the-loop notifications" for the
full HA-side wiring (packages/water_meter.yaml).

Deliberately trusts the human's value outright, including a *decrease* from
the current last_good - overriding the reader's own monotonic-increase
safety net is the entire point: this exists to fix exactly the case where
last_good itself was the wrong (too-high) value, which happened for real on
2026-09-27 and needed a manual SSH fix. A human confirming via their own
phone, having looked at the actual crop image in the notification, is a
stronger signal than any automated heuristic here.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import capture, sanity
from .config import CalibrationConfig, ConnectionConfig, connection_config_from_env

LOG = logging.getLogger(__name__)

DEFAULT_PORT = 8091
# Generous but not unbounded - rejects obvious garbage (a negative number,
# a fat-fingered extra digit) without hardcoding assumptions about this
# meter's current value range the way the VLM few-shot examples do.
MAX_PLAUSIBLE_VALUE = 10_000_000.0

# How many human-confirmed (image, digits) pairs to keep for ocr.py's
# dynamic few-shot prompt (see load_dynamic_examples) - bounded so the
# folder and the prompt's context usage don't grow forever. Only the most
# recent entries are kept; older image files are deleted as they age out.
DYNAMIC_EXAMPLES_LIMIT = 12


def _record_dynamic_example(
    connection: ConnectionConfig, calibration: CalibrationConfig, value: float, now: datetime
) -> None:
    """Save this human-confirmed (crop, digits) pair for ocr.py's dynamic
    few-shot prompt.

    Best-effort and silent on failure (missing crop file, bad calibration) -
    this is a nice-to-have accuracy improvement, not part of the correction
    itself, and must never make an otherwise-successful correction fail.
    """
    crop_path = connection.image_dir / "latest_crop.jpg"
    if not crop_path.exists():
        return
    try:
        digits = str(round(value * 10**calibration.decimal_places)).zfill(calibration.digit_count)
    except (ValueError, OverflowError):
        return

    examples_dir = connection.image_dir / "human_corrections"
    examples_dir.mkdir(parents=True, exist_ok=True)
    index_path = examples_dir / "index.json"
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError):
        entries = []

    file_name = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{digits}.jpg"
    try:
        (examples_dir / file_name).write_bytes(crop_path.read_bytes())
    except OSError:
        LOG.exception("Failed to save dynamic few-shot example")
        return
    entries.append({"file": file_name, "digits": digits})

    while len(entries) > DYNAMIC_EXAMPLES_LIMIT:
        stale = entries.pop(0)
        try:
            (examples_dir / str(stale["file"])).unlink(missing_ok=True)
        except (OSError, KeyError, TypeError):
            pass

    index_path.write_text(json.dumps(entries), encoding="utf-8")


def apply_correction(
    connection: ConnectionConfig,
    value: float,
    now: datetime | None = None,
    calibration: CalibrationConfig | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    previous = sanity.load_last_good(connection.state_dir)
    new_last_good = sanity.next_last_good(value, previous, history_limit=200, now=now)
    sanity.save_last_good(connection.state_dir, new_last_good)
    LOG.info("Applied human-approved correction: %s -> %s", previous.value if previous else None, value)

    from paho.mqtt import publish as mqtt_publish

    messages = [
        {"topic": connection.reading_topic, "payload": str(value), "retain": True},
        {"topic": connection.last_reading_time_topic, "payload": now.isoformat(), "retain": True},
        {"topic": connection.status_topic, "payload": "ok", "retain": True},
    ]
    capture.publish_with_retry(
        lambda: mqtt_publish.multiple(
            messages,
            hostname=connection.mqtt_host,
            port=connection.mqtt_port,
            auth=capture.mqtt_auth(connection),
        )
    )

    if calibration is not None:
        _record_dynamic_example(connection, calibration, value, now)


def _make_handler(
    connection: ConnectionConfig, token: str, calibration: CalibrationConfig | None = None
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's naming convention)
            # Serves the same crop the OCR pipeline actually read, for the
            # notification's image attachment (reader.py's
            # _notify_ha_of_unresolved_reading) - a mobile-app notification
            # fetches its image with a plain GET (no custom headers), so the
            # shared secret has to travel as a query param here rather than
            # an Authorization header like POST /correction uses.
            path, _, query = self.path.partition("?")
            if path != "/crop":
                self.send_response(404)
                self.end_headers()
                return
            params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
            if params.get("token") != token:
                self.send_response(401)
                self.end_headers()
                return
            crop_path = connection.image_dir / "latest_crop.jpg"
            try:
                image_bytes = crop_path.read_bytes()
            except OSError:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(image_bytes)))
            self.end_headers()
            self.wfile.write(image_bytes)

        def do_POST(self) -> None:  # noqa: N802 (http.server's naming convention)
            if self.path != "/correction":
                self.send_response(404)
                self.end_headers()
                return

            if self.headers.get("Authorization") != f"Bearer {token}":
                self.send_response(401)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
                value = float(body["value"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self.send_response(400)
                self.end_headers()
                return

            if not (0.0 <= value <= MAX_PLAUSIBLE_VALUE):
                self.send_response(400)
                self.end_headers()
                return

            try:
                apply_correction(connection, value, calibration=calibration)
            except Exception:
                LOG.exception("Failed to apply correction")
                self.send_response(500)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "value": value}).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            LOG.info("%s - %s", self.address_string(), format % args)

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    connection = connection_config_from_env()

    token = os.environ.get("WATER_METER_CORRECTION_TOKEN")
    if not token:
        sys.exit(
            "WATER_METER_CORRECTION_TOKEN must be set - refusing to run an "
            "unauthenticated listener that can rewrite the water meter's state"
        )

    from .config import load_calibration_config

    try:
        calibration = load_calibration_config(connection.calibration_path)
    except (OSError, ValueError):
        LOG.warning(
            "Could not load calibration from %s - corrections will still apply, but "
            "won't be saved as dynamic few-shot examples",
            connection.calibration_path,
        )
        calibration = None

    port = int(os.environ.get("WATER_METER_CORRECTION_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(connection, token, calibration))
    LOG.info("Water meter correction listener running on port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
