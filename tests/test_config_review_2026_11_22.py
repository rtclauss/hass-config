"""Regression tests for the 2026-11-22 full configuration review fixes."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates HA tags such as !secret and !include."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _load(relative: str) -> dict:
    return yaml.load((ROOT / relative).read_text(encoding="utf-8"), Loader=_Loader)


def _automation(relative: str, automation_id: str) -> dict:
    for automation in _load(relative)["automation"]:
        if automation.get("id") == automation_id:
            return automation
    raise AssertionError(f"automation {automation_id!r} not found in {relative}")


def test_christmas_season_keeps_registry_unique_id() -> None:
    # Without this unique_id HA created binary_sensor.christmas_season_2 and the
    # original entity, which every holiday consumer reads, stayed unavailable.
    sensors = [
        sensor
        for block in _load("packages/holidays.yaml")["template"]
        for sensor in block.get("binary_sensor", [])
        if sensor.get("default_entity_id") == "binary_sensor.christmas_season"
    ]
    assert len(sensors) == 1
    assert sensors[0]["unique_id"] == "christmas_season"


def test_lava_lamp_uses_native_offset_time_triggers() -> None:
    automation = _automation("packages/workday.yaml", "toggle_lava_lamp_workday")
    triggers = {trigger["id"]: trigger for trigger in automation["trigger"]}

    assert set(triggers) == {"lava-lamp-on", "lava-lamp-off"}
    for trigger in triggers.values():
        assert trigger["trigger"] == "time"
        assert trigger["at"]["entity_id"] == "input_datetime.next_work_meeting"

    assert triggers["lava-lamp-on"]["at"]["offset"] == "-01:00:00"
    assert triggers["lava-lamp-off"]["at"]["offset"] == "09:00:00"
    # The old templates did hour arithmetic that produced invalid times.
    assert "strptime" not in str(automation["trigger"])
    assert "sensor.time" not in str(automation["trigger"])


def test_tv_bed_prep_drops_overlapping_triggers_silently() -> None:
    automation = _automation("packages/tv.yaml", "tv_off_at_night_bed_prep")
    assert automation.get("mode", "single") == "single"
    assert automation["max_exceeded"] == "silent"
