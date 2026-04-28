from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path

from .payload import payload_hash, validate_payload
from .renderer import render_payload


LOG = logging.getLogger(__name__)
DEFAULT_TOPIC = "home/inky/owner_suite/state"


@dataclass(frozen=True)
class ServiceConfig:
    display_id: str
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str
    cache_dir: Path
    mqtt_username: str
    mqtt_password: str


@dataclass(frozen=True)
class ProcessResult:
    rendered: bool
    reason: str
    content_hash: str
    image_path: Path | None


class PayloadCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.payload_path = cache_dir / "last_payload.json"
        self.image_path = cache_dir / "last_image.png"
        self.hash_path = cache_dir / "last_hash.txt"

    def last_hash(self) -> str:
        if not self.hash_path.exists():
            return ""
        return self.hash_path.read_text(encoding="utf-8").strip()

    def restore_image(self) -> bytes | None:
        if not self.image_path.exists():
            return None
        return self.image_path.read_bytes()

    def save(self, raw_payload: str, image: bytes, content_hash: str) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.payload_path.write_text(raw_payload, encoding="utf-8")
        self.image_path.write_bytes(image)
        self.hash_path.write_text(content_hash, encoding="utf-8")
        return self.image_path


def config_from_env() -> ServiceConfig:
    return ServiceConfig(
        display_id=os.environ.get("INKY_DISPLAY_ID", "owner_suite"),
        mqtt_host=os.environ.get("INKY_MQTT_HOST", "localhost"),
        mqtt_port=int(os.environ.get("INKY_MQTT_PORT", "1883")),
        mqtt_topic=os.environ.get("INKY_MQTT_TOPIC", DEFAULT_TOPIC),
        cache_dir=Path(os.environ.get("INKY_CACHE_DIR", ".inky-cache")),
        mqtt_username=os.environ.get("INKY_MQTT_USERNAME", ""),
        mqtt_password=os.environ.get("INKY_MQTT_PASSWORD", ""),
    )


def process_payload(raw_payload: bytes | str, cache: PayloadCache, display_id: str) -> ProcessResult:
    raw_text = _decode_payload(raw_payload)
    try:
        data = json.loads(raw_text)
        payload = validate_payload(data)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        LOG.warning("Ignoring invalid Inky payload: %s", error)
        return ProcessResult(False, "invalid", "", None)

    if payload.display_id != display_id:
        LOG.warning("Ignoring payload for display_id=%s", payload.display_id)
        return ProcessResult(False, "wrong-display", payload_hash(payload), None)

    content_hash = payload_hash(payload)
    if content_hash == cache.last_hash():
        return ProcessResult(False, "duplicate", content_hash, cache.image_path)

    image = render_payload(payload)
    image_path = cache.save(raw_text, image, content_hash)
    return ProcessResult(True, "rendered", content_hash, image_path)


def run_mqtt_service(config: ServiceConfig) -> None:
    try:
        from paho.mqtt import client as mqtt
    except ImportError as error:
        raise RuntimeError("Install paho-mqtt on the Raspberry Pi to run the MQTT service.") from error

    cache = PayloadCache(config.cache_dir)
    restored = cache.restore_image()
    if restored is not None:
        LOG.info("Restored cached image from %s", cache.image_path)

    client = mqtt.Client()
    if config.mqtt_username:
        client.username_pw_set(config.mqtt_username, config.mqtt_password)

    def on_connect(client, _userdata, _flags, reason_code, _properties=None) -> None:
        if int(reason_code) == 0:
            LOG.info("Connected to MQTT broker %s:%s", config.mqtt_host, config.mqtt_port)
            client.subscribe(config.mqtt_topic)
            return
        LOG.error("MQTT connection failed with code %s", reason_code)

    def on_message(_client, _userdata, message) -> None:
        result = process_payload(message.payload, cache, config.display_id)
        LOG.info("Processed MQTT payload from %s: %s", message.topic, result.reason)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(config.mqtt_host, config.mqtt_port)
    client.loop_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MQTT-backed Inky display renderer service.")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Load environment configuration and exit without connecting to MQTT.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=os.environ.get("INKY_LOG_LEVEL", "INFO"))
    config = config_from_env()
    if args.check_config:
        LOG.info("Loaded Inky service config for display_id=%s topic=%s", config.display_id, config.mqtt_topic)
        return
    run_mqtt_service(config)


def _decode_payload(raw_payload: bytes | str) -> str:
    if isinstance(raw_payload, bytes):
        return raw_payload.decode("utf-8")
    return raw_payload


if __name__ == "__main__":
    main()
