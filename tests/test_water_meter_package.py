from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

PACKAGE_PATH = Path(__file__).resolve().parents[1] / "packages" / "water_meter.yaml"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def _package() -> dict:
    return yaml.safe_load(PACKAGE_PATH.read_text(encoding="utf-8"))


def _mqtt_sensors() -> dict[str, dict]:
    sensors = [s for block in _package()["mqtt"] for s in block.get("sensor", [])]
    return {s["unique_id"]: s for s in sensors}


def _problem_sensor() -> dict:
    return _package()["template"][0]["binary_sensor"][0]


def _automation() -> dict:
    return next(
        a for a in _package()["automation"] if a["id"] == "water_meter_reader_problem_alert"
    )


def _as_datetime(value, default=None):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _render_problem(status: str, last_reading_time: str) -> bool:
    states = {
        "sensor.water_meter_status": status,
        "sensor.water_meter_last_reading_time": last_reading_time,
    }
    env = Environment(undefined=StrictUndefined)
    env.filters["as_datetime"] = _as_datetime
    template = env.from_string(_problem_sensor()["state"])
    rendered = template.render(
        states=lambda entity_id: states[entity_id], now=lambda: NOW, timedelta=timedelta
    ).strip()
    assert rendered in ("True", "False")
    return rendered == "True"


def test_status_and_timestamp_sensors_attach_to_the_reader_device() -> None:
    sensors = _mqtt_sensors()

    status = sensors["water_meter_status"]
    assert status["state_topic"] == "waterreader/sensor/water_meter/status"
    assert status["default_entity_id"] == "sensor.water_meter_status"

    last = sensors["water_meter_last_reading_time"]
    assert last["state_topic"] == "waterreader/sensor/water_meter/last_reading_time"
    assert last["device_class"] == "timestamp"
    assert last["default_entity_id"] == "sensor.water_meter_last_reading_time"

    for sensor in (status, last):
        # Same identifier as the reader's own discovery payload, so these join
        # the existing "Water Meter Reader" device instead of creating one.
        assert sensor["device"] == {"identifiers": ["water_meter_reader"]}
        assert sensor["entity_category"] == "diagnostic"
        # No availability/expiry: staleness is judged from the reader's
        # timestamp, which survives a restart as a retained message.
        assert "expire_after" not in sensor
        assert "availability_topic" not in sensor


def test_problem_sensor_waits_out_a_single_bad_run() -> None:
    sensor = _problem_sensor()

    assert sensor["default_entity_id"] == "binary_sensor.water_meter_reader_problem"
    assert sensor["device_class"] == "problem"
    # The reader runs every 20 minutes, so 30 minutes needs two bad runs.
    assert sensor["delay_on"] == {"minutes": 30}


@pytest.mark.parametrize(
    ("status", "age", "expected"),
    [
        ("ok", timedelta(minutes=20), False),
        ("ok", timedelta(minutes=59), False),
        ("ok", timedelta(minutes=61), True),
        ("error:not a reading: dark or blank frame", timedelta(minutes=20), True),
        ("error:stuck: unchanged for the full history window", timedelta(minutes=5), True),
    ],
)
def test_problem_template_flags_stale_or_error_readings(
    status: str, age: timedelta, expected: bool
) -> None:
    assert _render_problem(status, (NOW - age).isoformat()) is expected


@pytest.mark.parametrize("missing", ["unknown", "unavailable"])
def test_problem_template_treats_a_missing_timestamp_as_a_problem(missing: str) -> None:
    assert _render_problem("ok", missing) is True


def test_alert_notifies_on_problem_and_recovery() -> None:
    automation = _automation()

    triggers = {t["id"]: t for t in automation["triggers"]}
    assert triggers["problem"]["entity_id"] == "binary_sensor.water_meter_reader_problem"
    assert triggers["problem"]["to"] == "on"
    assert triggers["recovered"]["from"] == "on"
    assert triggers["recovered"]["to"] == "off"

    branches = {
        branch["conditions"][0]["id"]: [step["action"] for step in branch["sequence"]]
        for branch in automation["actions"][0]["choose"]
    }
    assert branches["problem"] == ["persistent_notification.create", "notify.all"]
    assert branches["recovered"] == ["persistent_notification.dismiss", "notify.all"]


def test_package_contains_no_private_endpoints() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "10.24." not in text
    assert "192.168." not in text
    assert "!secret" not in text
    assert "mobile_app_" not in text
