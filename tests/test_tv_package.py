from __future__ import annotations

import re
from pathlib import Path


TV_PATH = Path(__file__).resolve().parents[1] / "packages" / "tv.yaml"


def _customize_block(entity_id: str) -> str:
    lines = TV_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"    {entity_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find customize block {entity_id!r} in {TV_PATH.name}")

    end = len(lines)
    next_entry = re.compile(r"^    [A-Za-z0-9_.]+:$")
    for index in range(start + 1, len(lines)):
        if next_entry.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def _script_block(script_id: str) -> str:
    lines = TV_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r} in {TV_PATH.name}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def _automation_block(automation_id: str) -> str:
    lines = TV_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line != f"  - id: {automation_id}":
            continue
        start = index
        break

    if start is None:
        raise AssertionError(f"Could not find automation id {automation_id!r} in {TV_PATH.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - id: "):
            end = index
            break

    return "\n".join(lines[start:end])


def _scene_block(scene_name: str) -> str:
    lines = TV_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line != f"  - name: {scene_name}":
            continue
        start = index
        break

    if start is None:
        raise AssertionError(f"Could not find scene {scene_name!r} in {TV_PATH.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - name: "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_all_watch_scripts_are_exposed_to_siri_and_voice_integrations() -> None:
    package = TV_PATH.read_text(encoding="utf-8")
    watch_scripts = set(re.findall(r"^  (watch_[a-z0-9_]+):$", package, flags=re.MULTILINE))
    exposed_scripts = {
        line.removeprefix("    script.").removesuffix(":")
        for line in package.splitlines()
        if line.startswith("    script.watch_")
    }

    assert exposed_scripts == watch_scripts

    for script_id in sorted(watch_scripts):
        block = _customize_block(f"script.{script_id}")

        assert "<<: *expose" in block
        assert 'friendly_name: "' in block


def test_watch_f1_script_uses_basement_apple_tv_path() -> None:
    f1_block = _script_block("watch_f1")

    assert "entity_id: media_player.basement" in f1_block
    assert 'source: "F1 TV"' in f1_block
    assert "action: script.music_assistant_pause_house_audio" in f1_block

    # Startup steps may be inlined or delegated to watch_basement_tv_startup
    if "action: script.watch_basement_tv_startup" in f1_block:
        startup_block = _script_block("watch_basement_tv_startup")
        assert 'source: "HDMI 3"' in startup_block
        assert "action: script.wait_for_basement_media_player_ready" in startup_block
    else:
        assert 'source: "HDMI 3"' in f1_block
        assert "action: script.wait_for_basement_media_player_ready" in f1_block


def test_tv_paused_scene_only_restores_basement_great_room_lighting() -> None:
    block = _scene_block("tv_paused")

    assert 'light.basement_great_room:\n        state: "on"\n        brightness: 128' in block
    assert "light.kitchen_sink_overhead" not in block
    assert "light.den_floods" not in block


def test_tv_resumed_automation_uses_basement_scene_instead_of_whole_house_light_sweep() -> None:
    block = _automation_block("tv_resumed")

    assert "action: scene.turn_on" in block
    assert "entity_id: scene.tv_resumed" in block
    assert "action: script.lights_off_except" not in block


def test_tv_resumed_scene_only_targets_basement_great_room() -> None:
    block = _scene_block("tv_resumed")

    assert 'light.basement_great_room:\n        state: "off"' in block
    assert "light.kitchen_all" not in block
    assert "light.hall_all" not in block
    assert "light.den_all" not in block
    assert "light.office_all" not in block
    assert "light.deck_string" not in block
