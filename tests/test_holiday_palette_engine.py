from __future__ import annotations

import json
from pathlib import Path


HOLIDAYS_PATH = Path(__file__).resolve().parents[1] / "packages" / "holidays.yaml"

EXPECTED_DYNAMIC_HOLIDAYS = {
    "burns_night",
    "national_curling_month",
    "groundhog_day",
    "presidents_day",
    "leap_day",
    "pi_day",
    "tartan_day",
    "star_wars_day",
    "minnesota_fishing_opener",
    "minnesota_statehood_day",
    "memorial_day",
    "juneteenth",
    "independence_day",
    "labor_day",
    "sealand_independence_day",
    "talk_like_a_pirate_day",
    "veterans_day",
    "thanksgiving",
    "hogmanay",
}


def _extract_block_scalar(name: str) -> str:
    lines = HOLIDAYS_PATH.read_text(encoding="utf-8").splitlines()
    marker = f"          {name}: >-"

    for index, line in enumerate(lines):
        if line != marker:
            continue

        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.startswith("            "):
                body.append(candidate[12:])
                continue
            break
        return "\n".join(body)

    raise AssertionError(f"Could not find block scalar {name!r}")


def _holiday_definitions() -> dict[str, dict[str, object]]:
    return json.loads(_extract_block_scalar("holiday_definitions_json"))


def _holiday_target_groups() -> dict[str, list[str]]:
    return json.loads(_extract_block_scalar("holiday_target_groups_json"))


def _expand_scene(
    definition: dict[str, object], scene_position: int, targets: dict[str, list[str]]
) -> dict[str, dict[str, object]]:
    entities: dict[str, dict[str, object]] = {}
    facade_palette = definition["facade_palette"]
    ambient_palette = definition["ambient_palette"]
    path_palette = definition["path_palette"]

    assert isinstance(facade_palette, list)
    assert isinstance(ambient_palette, list)
    assert isinstance(path_palette, list)

    for index, entity_id in enumerate(targets["facade_rgb_lights"]):
        attrs = dict(facade_palette[(index + scene_position) % len(facade_palette)])
        attrs["state"] = "on"
        entities[entity_id] = attrs

    ambient_attrs = dict(ambient_palette[scene_position % len(ambient_palette)])
    ambient_attrs["state"] = "on"
    for entity_id in targets["front_ambient_light"]:
        entities[entity_id] = dict(ambient_attrs)

    for index, entity_id in enumerate(targets["accent_path_lights"]):
        attrs = dict(path_palette[(index + scene_position) % len(path_palette)])
        attrs["state"] = "on"
        entities[entity_id] = attrs

    return entities


def test_dynamic_holiday_definitions_cover_issue_244_observances() -> None:
    definitions = _holiday_definitions()

    assert set(definitions) == EXPECTED_DYNAMIC_HOLIDAYS


def test_dynamic_holiday_definitions_include_target_behaviors_and_palette_counts() -> None:
    definitions = _holiday_definitions()

    for holiday_key, definition in definitions.items():
        assert definition["scene_count"] in {3, 4}, holiday_key
        assert set(definition["target_behaviors"]) == {
            "facade_rgb_lights",
            "front_ambient_light",
            "accent_path_lights",
        }, holiday_key
        assert len(definition["facade_palette"]) >= definition["scene_count"], holiday_key
        assert len(definition["ambient_palette"]) >= definition["scene_count"], holiday_key
        assert len(definition["path_palette"]) >= definition["scene_count"], holiday_key


def test_dynamic_holiday_rotation_reaches_every_declared_scene_index() -> None:
    definitions = _holiday_definitions()

    for holiday_key, definition in definitions.items():
        scene_count = definition["scene_count"]
        cadence = definition["cadence_minutes"]
        reachable_indexes = {
            ((minute // cadence) % scene_count) + 1 for minute in range(60)
        }

        assert reachable_indexes == set(range(1, scene_count + 1)), holiday_key

        midnight_window = definition.get("midnight_window")
        if midnight_window is None:
            continue

        fast_indexes = {
            ((minute // midnight_window["cadence_minutes"]) % scene_count) + 1
            for minute in range(midnight_window["start_minute"], 60)
        }
        assert fast_indexes == set(range(1, scene_count + 1)), holiday_key


def test_dynamic_holiday_target_groups_match_current_front_of_house_baseline() -> None:
    target_groups = _holiday_target_groups()

    assert target_groups == {
        "facade_rgb_lights": [
            "light.outside_front_door",
            "light.outside_north_west_garage",
            "light.outside_south_west_garage",
        ],
        "front_ambient_light": ["light.outside_front_hue"],
        "accent_path_lights": [],
    }


def test_dynamic_holiday_target_expansion_supports_optional_path_lights() -> None:
    definitions = _holiday_definitions()
    targets = _holiday_target_groups()
    holiday = definitions["burns_night"]

    baseline_entities = _expand_scene(holiday, scene_position=1, targets=targets)
    assert set(baseline_entities) == {
        "light.outside_front_door",
        "light.outside_north_west_garage",
        "light.outside_south_west_garage",
        "light.outside_front_hue",
    }

    expanded_targets = {
        **targets,
        "accent_path_lights": [
            "light.path_1",
            "light.path_2",
            "light.path_3",
            "light.path_4",
        ],
    }
    expanded_entities = _expand_scene(holiday, scene_position=1, targets=expanded_targets)

    assert set(expanded_entities) == {
        "light.outside_front_door",
        "light.outside_north_west_garage",
        "light.outside_south_west_garage",
        "light.outside_front_hue",
        "light.path_1",
        "light.path_2",
        "light.path_3",
        "light.path_4",
    }
    assert expanded_entities["light.path_1"]["state"] == "on"
    assert expanded_entities["light.path_1"] == {
        **holiday["path_palette"][1],
        "state": "on",
    }
    assert expanded_entities["light.path_4"] == {
        **holiday["path_palette"][1],
        "state": "on",
    }
