from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIMATE_PATH = ROOT / "packages" / "climate.yaml"
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _threshold_binary_sensor_block(text: str, sensor_name: str) -> str:
    marker = f"  - platform: threshold\n    name: {sensor_name}\n"
    start = text.index(marker)
    next_sensor = text.find("\n  - platform:", start + len(marker))
    if next_sensor == -1:
        return text[start:]
    return text[start:next_sensor]


def _template_sensor_block(text: str, sensor_name: str) -> str:
    marker = f"      - name: {sensor_name}\n"
    start = text.index(marker)
    next_sensor = text.find("\n      - name:", start + len(marker))
    if next_sensor == -1:
        return text[start:]
    return text[start:next_sensor]


def _template_unique_id_block(text: str, unique_id: str) -> str:
    marker = f"        unique_id: {unique_id}\n"
    start = text.rfind("\n      - ", 0, text.index(marker))
    next_sensor = text.find("\n      - ", start + len("\n      - "))
    if next_sensor == -1:
        return text[start:]
    return text[start:next_sensor]


def test_bathroom_humidity_high_uses_delta_threshold_helpers() -> None:
    text = _text(CLIMATE_PATH)

    cases = {
        "bathroom_humidity_high_threshold": "sensor.bathroom_humidity_delta",
        "basement_bathroom_humidity_high_threshold": "sensor.basement_bathroom_humidity_delta",
        "guest_bathroom_humidity_high_threshold": "sensor.guest_bathroom_humidity_delta",
    }

    for binary_sensor, delta_sensor in cases.items():
        block = _threshold_binary_sensor_block(text, binary_sensor)
        assert f"entity_id: {delta_sensor}" in block
        assert "upper: 10" in block

    public_block = _template_unique_id_block(text, "bathroom_humidity_high")
    assert "unique_id: bathroom_humidity_high" in public_block
    assert "binary_sensor.bathroom_humidity_high_threshold" in public_block
    assert "states('sensor.average_house_humidity')|float(default=0) + 10" not in text


def test_bathroom_humidity_delta_sensors_have_availability_guards() -> None:
    text = _text(CLIMATE_PATH)

    cases = {
        "bathroom_humidity_delta": "sensor.owner_suite_bathroom_tph_humidity",
        "basement_bathroom_humidity_delta": "sensor.basement_bathroom_tph_humidity",
        "guest_bathroom_humidity_delta": "sensor.guest_bathroom_tph_humidity",
    }

    for delta_sensor, humidity_sensor in cases.items():
        block = _template_sensor_block(text, delta_sensor)
        assert f"has_value('{humidity_sensor}')" in block
        assert "has_value('sensor.average_house_humidity')" in block
        assert f"states('{humidity_sensor}') | float(default=0)" in block
        assert "states('sensor.average_house_humidity') | float(default=0)" in block
        assert "| round(" not in block


def test_any_egress_open_uses_native_threshold_helper() -> None:
    text = _text(ZIGBEE_ZWAVE_PATH)
    helper_block = _threshold_binary_sensor_block(text, "any_egress_open_threshold")
    public_block = _template_sensor_block(text, "any_egress_open")

    assert "entity_id: sensor.open_egress_points" in helper_block
    assert "device_class: opening" in helper_block
    assert "upper: 0" in helper_block
    assert "unique_id: any_egress_open" in public_block
    assert "binary_sensor.any_egress_open_threshold" in public_block
    assert 'state: "{{ states(\'sensor.open_egress_points\') | int(0) > 0 }}"' not in text
