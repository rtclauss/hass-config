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
    block = _script_block("watch_f1")

    for token in (
        "entity_id: media_player.basement",
        'source: "HDMI 3"',
        'source: "F1 TV"',
        "action: script.wait_for_basement_media_player_ready",
        "action: script.music_assistant_pause_house_audio",
    ):
        assert token in block
