from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLIMATE_PATH = ROOT / "packages" / "climate.yaml"

ECOBEE_ROOMS = ("basement", "bedroom", "den", "guest_room", "office")


class ConfigLoader(yaml.SafeLoader):
    """Preserve opaque HA tags without resolving secrets or includes."""


ConfigLoader.add_constructor(None, lambda loader, node: loader.construct_scalar(node))


def _sensors() -> list[dict]:
    config = yaml.load(CLIMATE_PATH.read_text(encoding="utf-8"), Loader=ConfigLoader)
    return config["sensor"]


def _filter_for(source: str) -> dict:
    matches = [
        s for s in _sensors() if s.get("platform") == "filter" and s.get("entity_id") == source
    ]
    assert len(matches) == 1, f"expected one filter sensor for {source}, found {len(matches)}"
    return matches[0]


def _average_house_temp() -> dict:
    matches = [
        s
        for s in _sensors()
        if s.get("platform") == "min_max" and s.get("name") == "average_house_temp"
    ]
    assert len(matches) == 1
    return matches[0]


def test_each_ecobee_room_sensor_has_an_outlier_filter() -> None:
    # The HomeKit Controller link to the ecobee drops ~1.5x/month; as it does,
    # every remote room sensor reports 212 deg F (100 deg C) for an instant
    # before going unavailable. Normal readings move 0.18 deg F per step, so a
    # median band of a few degrees rejects the spike without lagging real
    # changes.
    for room in ECOBEE_ROOMS:
        sensor = _filter_for(f"sensor.{room}_temperature_2")
        assert sensor["name"] == f"{room.replace('_', ' ').title()} Temperature Filtered"
        assert sensor["unique_id"] == f"{room}_temperature_filtered"
        (outlier,) = sensor["filters"]
        assert outlier["filter"] == "outlier"
        assert 3 <= outlier["window_size"] <= 9
        # Wide enough for any real between-reading change, far below the
        # ~140 deg F jump to 212 deg F.
        assert 2.0 <= outlier["radius"] <= 10.0


def test_average_house_temp_uses_filtered_ecobee_rooms_not_raw_homekit() -> None:
    members = _average_house_temp()["entity_ids"]
    for room in ECOBEE_ROOMS:
        assert f"sensor.{room}_temperature_filtered" in members
        assert f"sensor.{room}_temperature_2" not in members
