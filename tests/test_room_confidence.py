from __future__ import annotations

from pathlib import Path


ROOM_CONFIDENCE_PATH = Path(__file__).resolve().parents[1] / "packages" / "room_confidence.yaml"


def _room_confidence_text() -> str:
    return ROOM_CONFIDENCE_PATH.read_text(encoding="utf-8")


def _sensor_block(text: str, sensor_name: str) -> str:
    marker = f"      - name: {sensor_name}\n"
    start = text.index(marker)
    next_sensor = text.find("\n      - name:", start + len(marker))
    if next_sensor == -1:
        return text[start:]
    return text[start:next_sensor]


def test_dining_room_confidence_entities_are_registered() -> None:
    text = _room_confidence_text()

    assert "binary_sensor.dining_room_confident_occupancy:" in text
    assert "friendly_name: Dining room confidently occupied" in text
    assert "sensor.dining_room_room_confidence:" in text
    assert "friendly_name: Dining room room confidence" in text
    assert "icon: mdi:silverware-fork-knife" in text


def test_dining_room_confidence_uses_bermuda_area_without_local_motion_weight() -> None:
    text = _room_confidence_text()
    block = _sensor_block(text, "dining_room_room_confidence")

    assert "sensor.iphone_17_pro_area" in block
    assert "sensor.apple_watch_ultra_2_area" in block
    assert "dining_area_names = ['dining room', 'living room']" in block
    assert "score.value = score.value + 45" in block
    assert "score.value = score.value + 10" in block
    assert "score.value = score.value + 5" in block
    assert "binary_sensor.dining_room_bt_proxy_dining_room_bluetooth_proxy_status" in block
    assert "_occupancy" not in block
    assert "living room" in block


def test_dining_room_confident_occupancy_threshold_matches_other_rooms() -> None:
    text = _room_confidence_text()
    block = _sensor_block(text, "dining_room_confident_occupancy")

    assert "device_class: occupancy" in block
    assert 'state: "{{ states(\'sensor.dining_room_room_confidence\') | int(0) >= 50 }}"' in block


def test_dining_room_confidence_recomputes_when_proxy_status_changes() -> None:
    text = _room_confidence_text()
    trigger_block = text.split("    sensor:", 1)[0]

    assert "binary_sensor.dining_room_bt_proxy_dining_room_bluetooth_proxy_status" in trigger_block
