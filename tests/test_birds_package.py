from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BIRDS_PATH = ROOT / "packages" / "birds.yaml"


def test_garden_birds_sensor_decodes_html_escaped_json_without_using_raw_payload_as_state() -> None:
    text = BIRDS_PATH.read_text(encoding="utf-8")
    sensor_block = text.split('name: "Garden Birds"', 1)[1].split("########################", 1)[0]

    assert "raw_json = raw_value | replace('&#34;', '\"') | replace('&quot;', '\"')" in sensor_block
    assert "payload = raw_json | from_json(default={})" in sensor_block
    assert "payload.common_name is defined" in sensor_block
    assert "raw_value[:1] not in ['{', '[']" in sensor_block
    assert "states('sensor.garden_birds') | default('unknown', true)" in sensor_block


def test_garden_birds_sensor_normalizes_json_attributes_before_parsing() -> None:
    text = BIRDS_PATH.read_text(encoding="utf-8")
    sensor_block = text.split('name: "Garden Birds"', 1)[1].split("########################", 1)[0]

    assert "json_attributes_template" in sensor_block
    assert "{{ payload | tojson }}" in sensor_block
    assert "{}" in sensor_block
