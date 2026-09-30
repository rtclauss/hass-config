from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "water_meter.yaml"
DOC_PATH = ROOT / "docs" / "water_meter.md"
SERVICE_PATH = ROOT / "deploy" / "systemd" / "water-meter-reader.service"
TIMER_PATH = ROOT / "deploy" / "systemd" / "water-meter-reader.timer"


def _package_text() -> str:
    return PACKAGE_PATH.read_text(encoding="utf-8")


def _automation_block(automation_id: str) -> str:
    text = _package_text()
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_package_tags_new_entities_with_water_meter_package() -> None:
    text = _package_text()

    assert 'package: "water_meter"' in text
    for entity_id in (
        "sensor.water_meter_status",
        "sensor.water_meter_last_reading_time",
        "sensor.water_meter_reading_age",
    ):
        assert f"{entity_id}:" in text


def test_stale_alert_automation_watches_age_and_error_status() -> None:
    block = _automation_block("water_meter_reading_stale")

    assert "sensor.water_meter_reading_age" in block
    assert "sensor.water_meter_status" in block
    assert "notify.all" in block
    assert "persistent_notification.create" in block


def test_mqtt_sensors_match_documented_topics() -> None:
    text = _package_text()
    doc = DOC_PATH.read_text(encoding="utf-8")

    for topic in (
        "waterreader/sensor/water_meter/status",
        "waterreader/sensor/water_meter/last_reading_time",
    ):
        assert topic in text, f"packages/water_meter.yaml missing MQTT topic {topic!r}"
        assert topic in doc, f"docs/water_meter.md missing MQTT topic {topic!r}"

    # sensor.water_meter itself arrives via Pi-published discovery, not a
    # hand-authored mqtt: sensor block here - make sure nobody redefines it.
    assert 'name: "Water Meter"' not in text


def test_reading_age_template_sensor_depends_on_last_reading_time() -> None:
    text = _package_text()

    assert "name: water_meter_reading_age" in text
    assert "sensor.water_meter_last_reading_time" in text
    assert "unit_of_measurement: min" in text


def test_systemd_units_reference_the_documented_mqtt_topics() -> None:
    service = SERVICE_PATH.read_text(encoding="utf-8")

    assert "WATER_METER_READING_TOPIC=waterreader/sensor/water_meter/state" in service
    assert "WATER_METER_STATUS_TOPIC=waterreader/sensor/water_meter/status" in service
    assert "EnvironmentFile=/etc/water-meter/credentials.env" in service
    assert "Environment=WATER_METER_MQTT_PASSWORD=" not in service, (
        "MQTT password must not be committed to git - it belongs in the "
        "EnvironmentFile, not a tracked Environment= line"
    )

    timer = TIMER_PATH.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=" in timer
    assert "WantedBy=timers.target" in timer
