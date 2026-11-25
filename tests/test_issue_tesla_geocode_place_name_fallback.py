"""Calendar locations that lead with a place name must still geocode.

Apple Calendar writes a contact or venue location as "Name\nStreet\nCity ST ZIP".
Nominatim's free-form search returns an empty list when the query starts with a
name it does not know, so the planner scored a real out-of-town drive as
"travel time unavailable" and fell back to an assumed 60-minute, 0 mi trip.
The planner now retries with the place name dropped, then without the house
number.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import jinja2
import pytest


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def _query_template() -> str:
    text = CAR_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"\n( +)geocode_queries: >-\n(.*?)\n +- repeat:\n",
        text,
        re.DOTALL,
    )
    assert match is not None, "could not locate the geocode_queries template"
    return textwrap.dedent(match.group(2))


def _queries(location: str) -> list[str]:
    template = jinja2.Environment().from_string(_query_template())
    # HA renders the list with native typing; the rendered text is its repr.
    return ast.literal_eval(template.render(candidate_location=location).strip())


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (
            "Someone’s Home\n1236 30th Ave\nSmalltown MN 56000",
            [
                "Someone’s Home, 1236 30th Ave, Smalltown MN 56000",
                "1236 30th Ave, Smalltown MN 56000",
                "30th Ave, Smalltown MN 56000",
            ],
        ),
        (
            "Dentist Office, 123 Main St, Sampleville, MN 55000",
            [
                "Dentist Office, 123 Main St, Sampleville, MN 55000",
                "123 Main St, Sampleville, MN 55000",
                "Main St, Sampleville, MN 55000",
            ],
        ),
        (
            "123 Main St\r\nSampleville MN 55000",
            [
                "123 Main St, Sampleville MN 55000",
                "Main St, Sampleville MN 55000",
            ],
        ),
        ("Curling Club", ["Curling Club"]),
    ],
)
def test_place_name_and_house_number_fallbacks(location: str, expected: list[str]) -> None:
    assert _queries(location) == expected


def test_first_query_is_the_whole_location() -> None:
    # A location that already geocodes must keep geocoding on the first try.
    assert _queries("Sample Arena\n1 Rink Rd\nSampleville MN 55000")[0] == (
        "Sample Arena, 1 Rink Rd, Sampleville MN 55000"
    )


def test_retries_stop_at_first_hit_respect_rate_limit_and_reset_result() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")
    block = text[text.index("geocode_queries: >-") :]
    block = block[: block.index("action: waze_travel_time.get_travel_times")]

    assert 'for_each: "{{ geocode_queries }}"' in block
    assert "value_template: \"{{ candidate_coords.pair == '' }}\"" in block
    assert "value_template: \"{{ repeat.index > 1 }}\"" in block
    assert "seconds: 1" in block
    assert "candidate_geo_result: null" in block
    assert block.index("candidate_geo_result: null") < block.index(
        "action: rest_command.geocode_address"
    )
    assert 'query: "{{ repeat.item }}"' in block
    assert 'query: "{{ candidate_location }}"' not in text


def test_cache_is_still_keyed_by_the_original_location() -> None:
    # The fallback changes what is sent to Nominatim, not the cache key, so a
    # resolved location is still looked up once and reused across recomputes.
    text = CAR_PATH.read_text(encoding="utf-8")
    assert "geo_cache.get(candidate_location, '')" in text
