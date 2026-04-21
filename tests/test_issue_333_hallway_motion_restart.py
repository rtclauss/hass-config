from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIGHT_PATH = ROOT / "packages" / "light.yaml"


def _automation_block(path: Path, automation_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - (?:id|alias): {re.escape(automation_name)}\n(.*?)(?=^  - (?:id|alias): |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_name!r} in {path.name}")
    return match.group(0)


def _off_condition_durations(block: str) -> Counter[tuple[str, str]]:
    pattern = re.compile(
        r"entity_id:\n"
        r"((?:\s+- binary_sensor\.hall_(?:main_foyer_motion|upstairs_motion|transition_switch)_occupancy\n)+)"
        r"\s+state: \"off\"\n\s+for:\n\s+minutes: (\d+)"
    )
    durations: Counter[tuple[str, str]] = Counter()
    for entity_list, minutes in pattern.findall(block):
        for entity_id in re.findall(
            r"binary_sensor\.hall_(?:main_foyer_motion|upstairs_motion|transition_switch)_occupancy",
            entity_list,
        ):
            durations[(entity_id, minutes)] += 1
    return durations


def test_toggle_hallway_day_requires_both_sensors_to_stay_clear_for_15_minutes() -> None:
    block = _automation_block(LIGHT_PATH, "toggle_hallway_day")
    durations = _off_condition_durations(block)

    assert durations[("binary_sensor.hall_main_foyer_motion_occupancy", "15")] == 2
    assert durations[("binary_sensor.hall_upstairs_motion_occupancy", "15")] == 2


def test_hallway_night_turn_off_requires_full_quiet_window_from_both_sensors() -> None:
    block = _automation_block(LIGHT_PATH, "hallway_light_toggle_at_night")
    durations = _off_condition_durations(block)

    assert durations[("binary_sensor.hall_main_foyer_motion_occupancy", "3")] == 2
    assert durations[("binary_sensor.hall_main_foyer_motion_occupancy", "15")] == 2
    assert durations[("binary_sensor.hall_upstairs_motion_occupancy", "3")] == 2
    assert durations[("binary_sensor.hall_upstairs_motion_occupancy", "15")] == 2
