"""Known places resolve to their Home Assistant zone, not the geocoder.

Precedence for a located calendar event:
1. the manual coordinate override (soonest located event only)
2. a zone the location names: one whole line or comma part equals a zone name
3. the address cache / Nominatim geocoder (with place-name fallbacks)
4. a zone the title points at with "to <zone>" / "at <zone>", only when the
   address could not be found

zone.home is never a destination, and zone-derived coordinates are never
written into the address cache.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import jinja2
import pytest


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def _text() -> str:
    return CAR_PATH.read_text(encoding="utf-8")


def _variable_template(name: str) -> str:
    """Return the folded-scalar body of a `name: >-` script variable."""
    lines = _text().splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(rf"( +){re.escape(name)}: >-", line)
        if match is None:
            continue
        indent = len(match.group(1))
        body: list[str] = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        return "\n".join(body)
    raise AssertionError(f"could not find variable {name!r}")


def _env() -> jinja2.Environment:
    env = jinja2.Environment()
    env.filters["regex_replace"] = lambda value, find, replace="": re.sub(
        find, replace, str(value)
    )
    return env


def _zone(entity_id: str, name: str, lat: float | None = 44.0, lon: float | None = -93.0):
    return SimpleNamespace(
        entity_id=entity_id,
        object_id=entity_id.split(".", 1)[1],
        name=name,
        attributes={"latitude": lat, "longitude": lon},
    )


ZONES = [
    _zone("zone.home", "The Brewery", 44.7, -93.2),
    _zone("zone.parents", "Parents", 43.6, -94.8),
    _zone("zone.spcc", "St Paul Curling Club", 44.9, -93.1),
    _zone("zone.rochester", "Rochester", 44.0, -92.5),
    _zone("zone.work", "Work", 44.8, -93.3),
    _zone("zone.twincities", "Twin Cities", 44.95, -93.2),
    _zone("zone.broken", "Broken", None, None),
]


def _zone_destinations() -> list[dict]:
    rendered = _env().from_string(_variable_template("zone_destinations")).render(
        states=SimpleNamespace(zone=ZONES)
    )
    return ast.literal_eval(rendered.strip())


def _location_zone(location: str) -> str:
    rendered = _env().from_string(_variable_template("candidate_location_zone")).render(
        candidate_location=location, zone_destinations=_zone_destinations()
    )
    return ast.literal_eval(rendered.strip())["pair"]


def _title_zone(message: str) -> str:
    rendered = _env().from_string(_variable_template("candidate_title_zone")).render(
        repeat=SimpleNamespace(item={"message": message}),
        zone_destinations=_zone_destinations(),
    )
    return ast.literal_eval(rendered.strip())["pair"]


PARENTS = "43.6,-94.8"
SPCC = "44.9,-93.1"
WORK = "44.8,-93.3"


def test_zone_destinations_exclude_home_and_zones_without_coordinates() -> None:
    destinations = {z["entity_id"]: z for z in _zone_destinations()}

    assert "zone.home" not in destinations
    assert "zone.broken" not in destinations
    assert destinations["zone.parents"]["pair"] == PARENTS
    assert destinations["zone.spcc"]["names"] == ["st paul curling club", "spcc"]
    assert destinations["zone.twincities"]["names"] == ["twin cities", "twincities"]


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("St. Paul Curling Club\n470 Selby Ave\nSaint Paul MN 55102", SPCC),
        ("SPCC", SPCC),
        ("Parents", PARENTS),
        ("Dinner spot, Parents, Somewhere MN", PARENTS),
        # Substrings and partial parts never match.
        ("Mayo Clinic, Rochester MN", ""),
        ("Someone’s Home\n1236 30th Ave\nSmalltown MN 56000", ""),
        ("Workshop Cafe, 1 Main St", ""),
        ("", ""),
    ],
)
def test_location_must_name_a_zone_as_a_whole_part(location: str, expected: str) -> None:
    assert _location_zone(location) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Drive to parents", PARENTS),
        ("Thanksgiving at Parents", PARENTS),
        ("Practice at St. Paul Curling Club", SPCC),
        ("Drive to work", WORK),
        ("Drive to parents house", PARENTS),
        # A zone name that is not the destination of "to"/"at" never matches.
        ("Work trip to Chicago", ""),
        ("Dinner with parents at Olive Garden", ""),
        ("Back to the workshop", ""),
        ("", ""),
    ],
)
def test_title_needs_to_or_at_before_the_zone_name(message: str, expected: str) -> None:
    assert _title_zone(message) == expected


def _candidate_block() -> str:
    text = _text()
    start = text.index('for_each: "{{ candidates }}"')
    return text[start : text.index("trip_plan_json: >-", start)]


def test_precedence_override_then_location_zone_then_cache() -> None:
    block = _candidate_block()
    coords = block[block.index("                    candidate_coords: >-\n") :]
    coords = coords[: coords.index("- if:")]

    override = coords.index("destination_coords_override.pair")
    location_zone = coords.index("candidate_location_zone.pair")
    cache = coords.index("geo_cache.get(candidate_location, '')")
    assert override < location_zone < cache


def test_title_zone_is_only_a_fallback_after_geocoding() -> None:
    block = _candidate_block()

    geocode = block.index("action: rest_command.geocode_address")
    title_fallback = block.index(
        "value_template: \"{{ candidate_coords.pair == '' and candidate_title_zone.pair != '' }}\""
    )
    waze = block.index("action: waze_travel_time.get_travel_times")
    assert geocode < title_fallback < waze
    assert "candidate_coords_from_zone: true" in block[title_fallback:waze]


def test_zone_coordinates_are_never_cached() -> None:
    block = _candidate_block()
    cache_update = block[block.index("geo_cache: >-") :]
    cache_update = cache_update[: cache_update.index("scored_candidates: >-")]

    assert "candidate_coords_from_override" in cache_update
    assert "not (candidate_coords_from_zone in [true, 'true', 'True', 1, '1'])" in cache_update


def test_override_still_wins_over_a_location_zone() -> None:
    block = _candidate_block()
    flag = block[block.index("                    candidate_coords_from_zone: >-\n") :]
    flag = flag[: flag.index("candidate_coords: >-")]

    # The zone flag is false when the override applies, so the override's
    # coordinates stay uncached for the override's own reason, not the zone's.
    assert "not (destination_coords_override.pair != ''" in flag
    assert "candidate_location_zone.pair != ''" in flag
