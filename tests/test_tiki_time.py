from __future__ import annotations

import re
from pathlib import Path


TIKI_TIME_PATH = Path(__file__).resolve().parents[1] / "packages" / "tiki_time.yaml"


def _script_block(script_id: str) -> str:
    lines = TIKI_TIME_PATH.read_text(encoding="utf-8").splitlines()
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


def test_tiki_time_uses_shared_music_assistant_helpers() -> None:
    block = _script_block("tiki_time")

    assert "Start the Tiki Time party mode" in block
    assert "action: script.music_assistant_prepare_house_party_group" in block
    assert "action: script.music_assistant_play_item" in block
    assert 'media_item: "somafm://radio/tikitime"' in block
    assert "media_player.den_sonos_2" in block
    assert "media_player.basement" in block
    assert "source: Photos" in block
    assert "flash: short" in block
    assert "script.tiki_time_tropical_color_cycle" in block


def test_tiki_time_color_cycle_loops_while_party_music_is_active() -> None:
    block = _script_block("tiki_time_tropical_color_cycle")

    assert "Continuously rotate Tiki Time-capable lights" in block
    assert "wait_for_trigger:" in block
    assert "repeat:" in block
    assert "while:" in block
    assert 'state: "playing"' in block
    assert 'state: "buffering"' in block
    assert "tropical_palette:" in block
    assert "seconds: 20" in block


def test_tiki_time_color_cycle_targets_individual_color_lights() -> None:
    block = _script_block("tiki_time_tropical_color_cycle")

    for entity_id in (
        "light.basement_great_room_east_1",
        "light.basement_great_east_room_2",
        "light.basement_great_room_middle_1",
        "light.basement_great_room_middle_2",
        "light.basement_great_room_west_1",
        "light.basement_great_room_west_2",
        "light.basement_great_room_west_3",
        "light.basement_tv_bias",
        "light.kitchen_overhead_1",
        "light.kitchen_overhead_7",
        "light.kitchen_sink_overhead",
        "light.east_table_lamp",
        "light.west_table_lamp",
        "light.tiki_room_floor_lamp",
    ):
        assert entity_id in block

    assert "effect: rainbow" in block
    assert "entity_id: light.kitchen_all" not in block
    assert "entity_id: light.office_all" not in block


def test_tiki_time_is_exposed_to_voice_assistants() -> None:
    text = TIKI_TIME_PATH.read_text(encoding="utf-8")

    assert "script.tiki_time:" in text
    assert "haaska_hidden: false" in text
    assert "homebridge_hidden: false" in text
