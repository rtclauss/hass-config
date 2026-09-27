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
from .config import ConnectionConfig, connection_config_from_env

LOG = logging.getLogger(__name__)

DEFAULT_PORT = 8091
# Generous but not unbounded - rejects obvious garbage (a negative number,
# a fat-fingered extra digit) without hardcoding assumptions about this
# meter's current value range the way the VLM few-shot examples do.
MAX_PLAUSIBLE_VALUE = 10_000_000.0


def apply_correction(connection: ConnectionConfig, value: float, now: datetime | None = None) -> None:
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


def _make_handler(connection: ConnectionConfig, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
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
                apply_correction(connection, value)
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

    port = int(os.environ.get("WATER_METER_CORRECTION_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(connection, token))
    LOG.info("Water meter correction listener running on port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
