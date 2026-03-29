from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMERA_PATH = ROOT / "packages" / "camera.yaml"
CURLING_PATH = ROOT / "packages" / "curling.yaml"
HOLIDAYS_PATH = ROOT / "packages" / "holidays.yaml"
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"
WEATHER_PATH = ROOT / "packages" / "weather.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"


def _script_block(path: Path, script_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  {re.escape(script_name)}:\n(.*?)(?=^  [A-Za-z0-9_]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find script block {script_name!r} in {path.name}")
    return match.group(0)


def _group_block(path: Path, group_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  {re.escape(group_name)}:\n(.*?)(?=^  [A-Za-z0-9_]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find group block {group_name!r} in {path.name}")
    return match.group(0)


def _scene_block(scene_name: str) -> str:
    text = ZONE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - name: {re.escape(scene_name)}\n(.*?)(?=^  - name: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find scene block {scene_name!r}")
    return match.group(0)


def test_dynamic_action_scripts_use_explicit_native_actions() -> None:
    for path, script_name, action_name in (
        (CURLING_PATH, "toggle_curling_automation_on_curling_season", "automation.turn_on"),
        (HOLIDAYS_PATH, "toggle_christmas_automation_during_christmas_season", "automation.turn_on"),
        (WEATHER_PATH, "nws_dakota_county_alerts_popup_on_wx_alert", "persistent_notification.create"),
    ):
        block = _script_block(path, script_name)

        assert "action: >" not in block
        assert action_name in block

    weather_block = _script_block(WEATHER_PATH, "nws_dakota_county_alerts_popup_on_wx_alert")
    assert "persistent_notification.dismiss" in weather_block
    assert "condition: not" in weather_block
    assert 'state: "0"' in weather_block


def test_camera_security_references_use_current_entities() -> None:
    zone_text = ZONE_PATH.read_text(encoding="utf-8")
    house_mode_text = HOUSE_MODE_PATH.read_text(encoding="utf-8")

    for text in (zone_text, house_mode_text):
        assert "switch.living_room_camera" not in text
        assert "switch.basement_camera_power" not in text

    assert "switch.livingroom_motion_detection" in zone_text
    assert "switch.tiki_room_camera" in zone_text
    assert "switch.livingroom_motion_detection" in house_mode_text
    assert "switch.tiki_room_camera" in house_mode_text


def test_camera_scenes_toggle_current_camera_controls() -> None:
    arrive_home = _scene_block("arrive_home")
    turn_on_cameras = _scene_block("turn_on_cameras")

    for block, state in ((arrive_home, '"off"'), (turn_on_cameras, '"on"')):
        assert "switch.livingroom_motion_detection" in block
        assert "switch.tiki_room_camera" in block
        assert f"state: {state}" in block


def test_camera_status_groups_track_current_living_room_and_tiki_room_entities() -> None:
    livingroom_group = _group_block(CAMERA_PATH, "livingroom_camera_status")
    basement_group = _group_block(CAMERA_PATH, "basement_camera_status")

    for stale_entity_id in (
        "switch.livingroom_night_mode_auto",
        "switch.livingroom_mjpeg_rtsp_server",
        "switch.livingroom_h264_rtsp_server",
        "cover.livingroom_move_leftright",
        "cover.livingroom_move_updown",
        "switch.basement_motion_detection",
        "switch.basement_camera_power",
    ):
        assert stale_entity_id not in livingroom_group + basement_group

    for current_entity_id in (
        "switch.livingroom_auto_night_detection",
        "switch.livingroom_rtsp_server",
        "cover.livingroom_move_left_right",
        "cover.livingroom_move_up_down",
        "switch.tiki_room_camera",
        "switch.tikiroomcam_tikiroom_motion_detection",
        "switch.tikiroomcam_tikiroom_rtsp_server",
        "cover.tikiroomcam_tikiroom_move_left_right",
        "cover.tikiroomcam_tikiroom_move_up_down",
    ):
        assert current_entity_id in livingroom_group + basement_group


def test_stale_hallway_motion_entity_is_fully_replaced() -> None:
    light_text = LIGHT_PATH.read_text(encoding="utf-8")
    zigbee_zwave_text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    assert "binary_sensor.hallway_motion" not in light_text + zigbee_zwave_text
    assert "binary_sensor.hall_upstairs_motion_occupancy" in light_text
    assert "binary_sensor.hall_upstairs_motion_occupancy" in zigbee_zwave_text
