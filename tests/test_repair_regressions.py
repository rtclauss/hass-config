from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTIVE_LIGHTING_PATH = ROOT / "packages" / "adaptive_lighting.yaml"
CAMERA_PATH = ROOT / "packages" / "camera.yaml"
CURLING_PATH = ROOT / "packages" / "curling.yaml"
HOLIDAYS_PATH = ROOT / "packages" / "holidays.yaml"
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"
WEATHER_PATH = ROOT / "packages" / "weather.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
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


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


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
        (WEATHER_PATH, "nws_dakota_county_alerts_popup_on_wx_alert", "persistent_notification.create"),
    ):
        block = _script_block(path, script_name)

        assert "action: >" not in block
        assert action_name in block

    weather_block = _script_block(WEATHER_PATH, "nws_dakota_county_alerts_popup_on_wx_alert")
    assert "persistent_notification.dismiss" in weather_block
    assert "condition: not" in weather_block
    assert 'state: "0"' in weather_block

    holidays_text = HOLIDAYS_PATH.read_text(encoding="utf-8")
    assert "toggle_christmas_automation_during_christmas_season" not in holidays_text
    assert "automation.turn_on" not in holidays_text
    assert "automation.turn_off" not in holidays_text


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
    basement_group = _group_block(CAMERA_PATH, "tikiroom_camera_status")

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


def test_office_switch_actions_do_not_target_missing_adaptive_lighting_switch() -> None:
    block = _automation_block(ZIGBEE_ZWAVE_PATH, "office_switch_actions")
    adaptive_lighting_text = ADAPTIVE_LIGHTING_PATH.read_text(encoding="utf-8")

    assert "switch.adaptive_lighting_office" not in block
    assert "switch.adaptive_lighting_office" not in adaptive_lighting_text
    assert "action: script.adaptive_light_turn_on" not in block
    assert "action: light.turn_on" in block
    assert "entity_id: light.office_ceiling" in block


def test_ios_alarm_sync_preserves_manual_workday_alarm_overrides() -> None:
    block = _script_block(WORKDAY_PATH, "set_wakeup_from_phone_alarm")

    for helper in (
        "input_boolean.ios_synced_weekday_alarm",
        "input_boolean.ios_synced_special_meeting",
    ):
        assert helper in block

    assert "weekday_alarm_already_on" in block
    assert "special_meeting_already_on" in block
    assert "not weekday_alarm_already_on" in block
    assert "not special_meeting_already_on" in block
    assert "tomorrow_is_workday and is_state('input_boolean.ios_synced_weekday_alarm', 'on')" in block
    assert "tomorrow_is_workday and is_state('input_boolean.ios_synced_special_meeting', 'on')" in block
    assert re.search(
        r'action: input_boolean\.turn_off\s+target:\s+entity_id:\s+- input_boolean\.weekday_alarm_on\s+- input_boolean\.ios_synced_weekday_alarm',
        block,
    )
    assert re.search(
        r'action: input_boolean\.turn_off\s+target:\s+entity_id:\s+- input_boolean\.special_meeting\s+- input_boolean\.ios_synced_special_meeting',
        block,
    )
    assert re.search(
        r'action: input_boolean\.turn_off\s+target:\s+entity_id: input_boolean\.weekend_alarm_on',
        block,
    )
