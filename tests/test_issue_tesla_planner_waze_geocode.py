"""Regression tests for the Tesla planner's Waze coordinate/geocode handling.

Background: Waze blocked the address-autocomplete endpoint that
`pywaze` used to resolve an address string into coordinates
(eifinger/pywaze#119, home-assistant/core #191329 and #191667). Waze *routing*
still works perfectly by coordinate — `sensor.me_to_home` kept working
throughout because it is configured with a lat/lon pair — but
`waze_travel_time.get_travel_times` fails for any address input.

The planner passed addresses on both sides of the call:

  * origin      -> `input_text.home_address`
  * destination -> the calendar event's own `location` string

so every lookup failed. Because the Waze call is `continue_on_error: true`, a
failed candidate used to degrade to `distance_mi: 0`, which is below
`input_number.tesla_local_trip_threshold_mi` (default 10 mi). A real 69-mile
drive to a dentist in Rochester was therefore silently reclassified as a local
errand, `binary_sensor.upcoming_trip_charging` stayed `off`, and the planner
fell through to the alarm-only 85% tier with no preconditioning. The only
visible symptom was a plausible-looking charge limit.

Two fixes, both covered here:

1. Coordinates instead of addresses. The origin comes from `zone.home`'s own
   latitude/longitude (no geocoding needed at all), and the destination is
   geocoded via Nominatim through `rest_command.geocode_address`, cached on the
   sensor so a repeat recompute of the same event does not re-query OSM. An
   `input_text.tesla_destination_coords_override` is the manual escape hatch.

2. Fail safe, and say so. A *located* candidate whose travel time cannot be
   scored is no longer treated as 0 mi. It stays a qualifying trip (so
   preconditioning survives the outage) at the conservative sub-90-mile charge
   tier, using `input_number.tesla_degraded_travel_min` for departure timing,
   and sets a `scoring_degraded` flag that the planner summary surfaces. An
   event with *no* location is still legitimately not a trip.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PATH = ROOT / "packages" / "car.yaml"


def _candidate_scoring_block(text: str) -> str:
    block = re.search(
        r"      - repeat:\n          for_each: \"\{\{ candidates \}\}\"\n(.*?)\n      - variables:\n          trip_plan_json:",
        text,
        re.DOTALL,
    )
    assert block is not None, "could not locate the candidate scoring repeat block"
    return block.group(1)


def test_waze_origin_uses_zone_home_coordinates_not_an_address() -> None:
    # The origin never needs geocoding: zone.home already holds the
    # authoritative home position.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "{% set lat = state_attr('zone.home', 'latitude') %}" in text
    assert "{% set lon = state_attr('zone.home', 'longitude') %}" in text
    assert "'origin': planner_home_coords.pair," in text

    # The old address-based origin must be gone from the Waze call.
    assert "origin: \"{{ planner_home_address }}\"" not in text
    assert "planner_home_address:" not in text


def test_waze_destination_is_a_coordinate_pair() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")
    block = _candidate_scoring_block(text)

    assert "'destination': candidate_coords.pair," in block
    # Passing the raw calendar location string is what Waze now rejects.
    assert "destination: \"{{ repeat.item.location }}\"" not in block


def test_coordinates_never_reach_the_service_as_bare_scalars() -> None:
    # Codex P1 on PR #1199. A bare "lat,lon" template literal_evals into a
    # tuple under HA's native typing (verified on the live instance via the
    # WebSocket render_template API: the bare form returns
    # [44.761712, -93.203609], the same value inside a rendered mapping stays
    # a string, and a `| string` filter does NOT help because the parse
    # happens after rendering). waze_travel_time's schema uses TextSelector,
    # which strictly validates `str`, and a config-validation error bypasses
    # continue_on_error — so the bare form aborts the action outright.
    text = CAR_PATH.read_text(encoding="utf-8")

    # Coordinates are carried inside mappings, read back via `.pair`.
    assert "{{ {'pair': ''} }}" in text
    assert "planner_home_coords.pair" in text
    assert "candidate_coords.pair" in text

    # No bare-scalar service data for either side.
    assert "origin: \"{{ planner_home_coords }}\"" not in text
    assert "destination: \"{{ candidate_coords }}\"" not in text
    # The whole data mapping is rendered as one template instead.
    assert "data: >-" in text
    assert "'units': 'imperial'" in text


def test_manual_override_is_not_written_into_the_address_cache() -> None:
    # Codex P2 on PR #1199. Caching an override would mean clearing it never
    # restores real geocoding, and a second event at the same location would
    # inherit it despite the soonest-candidate-only scope.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "candidate_coords_from_override: false" in text
    assert (
        "and not (candidate_coords_from_override in [true, 'true', 'True', 1, '1'])"
        in text
    )


def test_geocode_rest_command_is_defined_with_a_contactable_user_agent() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "geocode_address:" in text
    assert "nominatim.openstreetmap.org/search" in text
    assert "format=jsonv2" in text
    assert "q={{ query | urlencode }}" in text
    # Nominatim's usage policy requires an identifying, contactable agent.
    assert (
        'User-Agent: "HomeAssistant rtclauss-hass-config;'
        " contact https://github.com/rtclauss\"" in text
    )


def test_geocode_response_is_guarded_against_mappings_and_empty_results() -> None:
    # Nominatim answers an error with a JSON *object*, and a no-match with an
    # empty list. Indexing [0] on either must not happen.
    text = CAR_PATH.read_text(encoding="utf-8")
    block = _candidate_scoring_block(text)

    assert (
        "{% if body is sequence and body is not mapping and (body | count) > 0"
        " and body[0].lat is defined %}" in block
    )


def test_geocode_results_are_cached_and_pruned() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    # Seeded from the sensor's own previous attributes, so a 15-minute
    # recompute of the same event reuses coordinates instead of re-querying.
    assert (
        "state_attr('binary_sensor.upcoming_trip_charging', 'geo_cache')" in text
    )
    assert (
        "geo_cache: \"{{ geo_cache_seed if geo_cache_seed is mapping else {} }}\""
        in text
    )
    assert "geo_cache.get(candidate_location, '')" in text
    # Only addresses still in play survive, so the cache cannot grow forever.
    assert "geo_cache_pruned:" in text


def test_manual_coordinate_override_helper_exists_and_targets_soonest() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "tesla_destination_coords_override:" in text
    assert "name: Tesla Destination Coordinates Override" in text
    assert (
        "states('input_text.tesla_destination_coords_override')" in text
    )
    # One "lat,lon" entry has to be unambiguous when several located events
    # share the window, so it targets the soonest located candidate.
    assert "override_target_start:" in text
    assert (
        "{% if destination_coords_override != ''"
        " and repeat.item.start == override_target_start %}" in text
    )


def test_unscorable_located_candidate_is_not_scored_as_zero_miles() -> None:
    # The core fail-open bug: a failed lookup must not look like a 0 mi errand.
    text = CAR_PATH.read_text(encoding="utf-8")
    block = _candidate_scoring_block(text)

    # Candidates carry an explicit scored flag through to selection.
    assert "candidate_scored: true" in block
    assert "candidate_scored: false" in block
    assert "scored=candidate_scored" in block

    # A located-but-unscored candidate still qualifies as a trip.
    assert (
        "{% set qualifies = (c_located and not c_scored)"
        " or (c_scored and c.distance_mi >= local_trip_threshold_mi) %}" in text
    )


def test_scored_flag_is_read_string_tolerantly() -> None:
    # HA template variables can surface a boolean as the string "False", which
    # is truthy. A bare `not c.scored` would silently mis-read that as scored.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "{% set c_scored = c.scored in [true, 'true', 'True', 1, '1'] %}" in text
    assert (
        "{% set next_scored = ns2.next.scored in [true, 'true', 'True', 1, '1'] %}"
        in text
    )


def test_event_without_a_location_is_still_not_a_trip() -> None:
    # Fail-safe applies only to events we *could* have scored. An event with no
    # location tells us nothing and must not start preconditioning.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert (
        "{% set c_located = (c.location | default('', true) | string | trim) != '' %}"
        in text
    )


def test_degraded_plan_uses_calibrated_fallback_duration() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "tesla_degraded_travel_min:" in text
    assert "name: Tesla Degraded Travel Fallback" in text
    assert "initial: 60" in text
    assert (
        "states('input_number.tesla_degraded_travel_min') | float(default=60)" in text
    )
    # Departure timing must not collapse to "start - buffer" when the drive
    # time is unknown, or preconditioning would begin after the real departure.
    assert (
        "'duration_min': ns2.next.duration_min if next_scored else degraded_travel_min,"
        in text
    )


def test_degraded_scoring_is_surfaced_not_silent() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "'scoring_degraded': ns2.degraded," in text
    assert "scoring_degraded: >-" in text
    assert (
        "state_attr('binary_sensor.upcoming_trip_charging', 'scoring_degraded')"
        in text
    )
    # The nightly/notification summary has to admit the numbers are assumed.
    assert "Travel time unavailable, so distance and departure are assumed" in text
    assert "'scoring_degraded': scoring_degraded" in text


def test_geo_cache_is_never_round_tripped_through_json() -> None:
    # Codex P1 on PR #1199. Home Assistant renders script variables with
    # native typing, so a `| to_json`'d mapping comes back as a dict and a
    # following `| from_json` raises, aborting the whole action before any
    # candidate is scored — worse than the bug being fixed. The cache's keys
    # and values are all strings, so both "{}" (first recompute) and
    # {"addr": "lat,lon"} (populated) literal_eval cleanly and hit this.
    #
    # The neighbouring *_json variables are safe only incidentally: their
    # payloads contain `false`, which literal_eval rejects, so they stay
    # strings. Do not rely on that for the cache — keep it a mapping.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "geo_cache_seed | from_json" not in text
    assert "geo_cache_pruned | from_json" not in text
    # No to_json on the cache either, in any spelling.
    for line in text.splitlines():
        if "geo_cache" in line:
            assert "to_json" not in line, f"cache serialized to JSON: {line.strip()}"
            assert "from_json" not in line, f"cache parsed from JSON: {line.strip()}"


def test_geo_cache_mapping_guards_are_present() -> None:
    # A non-mapping attribute (a restored string, a corrupted value) must
    # degrade to an empty cache rather than erroring the action.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "{{ cached if cached is mapping else {} }}" in text
    assert "{{ geo_cache_seed if geo_cache_seed is mapping else {} }}" in text
    assert "{{ geo_cache_pruned if geo_cache_pruned is mapping else {} }}" in text


def test_trip_plan_json_still_carries_a_literal_eval_blocking_value() -> None:
    # The *_json variables rely on `false` appearing in the payload so native
    # typing leaves them as strings for `| from_json`. If a future edit made
    # every value literal_eval-safe, those reads would break the same way the
    # cache did. Pin the property rather than the incidental key.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "'all_day': false," in text
    assert "(trip_plan_json | from_json)" in text
