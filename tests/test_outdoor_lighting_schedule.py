from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOUSE_MODE_PATH = ROOT / "packages" / "house_mode.yaml"
LIGHT_PATH = ROOT / "packages" / "light.yaml"


def _automation_block(path: Path, automation_id: str) -> str:
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")
    return match.group(0)


def _scene_block(scene_name: str) -> str:
    pattern = re.compile(
        rf"^  - name: {re.escape(scene_name)}\n(.*?)(?=^  - name: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(LIGHT_PATH.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"Could not find scene block {scene_name!r}")
    return match.group(0)


def _script_block(script_id: str) -> str:
    lines = HOUSE_MODE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def test_front_lights_toggle_dims_overnight_and_restores_before_sunrise() -> None:
    block = _automation_block(LIGHT_PATH, "front_lights_toggle")

    for token in (
        'id: late_night_dim',
        'at: "02:00:00"',
        'id: pre_sunrise',
        'offset: "-00:45:00"',
        'brightness_pct: 25',
        'id: sunrise',
        'action: light.turn_off',
    ):
        assert token in block

    assert block.count("brightness_pct: 100") >= 2


def test_house_transition_night_mode_uses_night_arrival_scene() -> None:
    block = _script_block("house_transition")

    assert "elif requested_mode == 'night'" in block
    assert "scene.night_arrive_home" in block


def test_night_arrive_home_scene_restores_full_brightness_exterior_lights() -> None:
    block = _scene_block("night_arrive_home")

    for token in (
        "light.outside_front_hue:",
        "light.outside_north_west_garage:",
        "light.outside_south_west_garage:",
        "light.outside_front_door:",
    ):
        assert token in block

    assert block.count("brightness: 255") >= 6
