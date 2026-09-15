"""Regression tests for the DIY-store restock prompts.

Background: a Home Depot trip produced no "buy air filters" notification. The
automation triggered on `sensor.zeke_place_place_name` being exactly one of a
handful of brand strings, or on `place_type` being exactly `doityourself`.

Three things had to line up for that to work, and none of them did:

* The Places integration only re-geocodes when the tracker reports a new GPS
  fix. The arrival fix lands in the parking lot, so `place_name` reads
  `unknown` and `place_type` reads `parking`. The phone then reports nothing
  for the rest of the visit, so the geocode is never retried.
* Real OSM names carry store numbers and suffixes, so equality against a bare
  brand string misses even when the store *is* named.
* Only the phone was watched; the car's identical sensors were ignored.

The fix moves detection into a shared `binary_sensor.diy_store_visit` and adds
an arrive-home backstop for the parking-lot case.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIMATE_PATH = ROOT / "packages" / "climate.yaml"
WATER_SOFTENER_PATH = ROOT / "packages" / "water_softener.yaml"
ZONE_PATH = ROOT / "packages" / "zone.yaml"

# The arrival backstop only fires after a trip long enough to have shopped.
ERRAND_THRESHOLD_SECONDS = 2700


def _automation_block(path: Path, automation_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")
    return match.group(0)


def _diy_store_sensor_block() -> str:
    text = ZONE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^      - name: diy_store_visit\n(.*?)(?=^      - name: |^########################)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError("Could not find template binary sensor 'diy_store_visit'")
    return match.group(0)


########################
# Shared detection sensor
########################


def test_diy_store_sensor_watches_both_trackers() -> None:
    block = _diy_store_sensor_block()

    # The car has the same Places sensors as the phone and was previously
    # ignored by the air-filter prompt.
    assert "for tracker in ['zeke', 'tesla']" in block


def test_diy_store_sensor_prefers_structured_osm_tagging() -> None:
    block = _diy_store_sensor_block()

    # The OSM key/value pair is the real category data. Read it from the
    # extended-data attributes rather than trusting a display name.
    assert "state_attr(extended, 'osm_dict')" in block
    assert "osm.get('class') == 'shop'" in block
    for shop_type in ("doityourself", "hardware", "trade", "paint", "garden_centre"):
        assert shop_type in block, f"missing shop type {shop_type!r}"


def test_diy_store_sensor_does_not_use_the_dead_category_sensor() -> None:
    block = _diy_store_sensor_block()

    # sensor.<tracker>_place_place_category reads osm_dict["category"], but
    # Nominatim's reverse endpoint returns that key as "class". The sensor has
    # been `unknown` on both trackers for the whole recorder window.
    assert "_place_place_category" not in block


def test_diy_store_sensor_excludes_department_stores_structurally() -> None:
    block = _diy_store_sensor_block()

    # shop=department_store is Target and Walmart as well as Fleet Farm, so it
    # must not be a structural match. Fleet Farm comes in via its brand tag.
    assert "department_store" not in block


def test_diy_store_sensor_reads_brand_tags() -> None:
    block = _diy_store_sensor_block()

    # brand/operator are curated OSM tags, not display names, so they are a
    # better fallback than place_name for stores tagged as something generic.
    assert "extratags.get('brand', '')" in block
    assert "extratags.get('operator', '')" in block


def test_diy_store_sensor_keeps_a_name_fallback() -> None:
    block = _diy_store_sensor_block()

    # Substring search, not equality, so "The Home Depot #2812" still matches.
    assert "labels | select('search', brand_pattern)" in block
    assert "| lower" in block
    for brand in ("home depot", "menards", "lowe's", "fleet farm", "ace hardware"):
        assert brand in block, f"missing store keyword {brand!r}"


def test_diy_store_sensor_name_fallback_has_no_generic_tokens() -> None:
    block = _diy_store_sensor_block()

    brand_list = block[block.index("set diy_brands") : block.index("brand_pattern =")]
    # A bare "hardware" substring would match on name alone; shop=hardware
    # already covers it structurally.
    assert "'hardware'" not in brand_list


def test_diy_store_sensor_degrades_without_extended_attributes() -> None:
    block = _diy_store_sensor_block()

    # If the integration's extended attributes are ever turned off, osm_dict is
    # empty and the plain place_type sensor has to carry the structured check.
    assert "states('sensor.' ~ tracker ~ '_place_place_type')" in block
    assert "osm.get('class') is none" in block


def test_diy_store_sensor_also_reads_zone_names() -> None:
    block = _diy_store_sensor_block()

    # Reading zone_name means store zones, if any are ever added, are picked up
    # by the same keyword list with no further wiring.
    assert "_place_zone_name" in block


def test_diy_store_sensor_holds_through_geocode_flicker() -> None:
    block = _diy_store_sensor_block()

    # A store fix can be a single sample between two parking-lot fixes. Holding
    # the sensor on keeps one visit to one prompt instead of several.
    assert "delay_off:" in block


########################
# Air filter prompt
########################


def test_air_filter_prompt_uses_shared_sensor_not_place_strings() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    assert "binary_sensor.diy_store_visit" in block
    assert "sensor.zeke_place_place_name" not in block
    assert "sensor.zeke_place_place_type" not in block


def test_air_filter_prompt_has_arrival_backstop() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    # The store signal misses entirely when the geocode lands in the parking
    # lot, so arriving home has to be able to ask too.
    assert "id: home_from_errand" in block
    assert "binary_sensor.bayesian_zeke_home" in block
    assert str(ERRAND_THRESHOLD_SECONDS) in block
    assert "trigger.from_state.last_changed" in block


def test_air_filter_prompt_backstop_does_not_gate_the_store_path() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    # Standing in the store should prompt immediately, not only after 45
    # minutes away, so the duration check must be skipped for that trigger.
    assert "trigger.id != 'home_from_errand'" in block


def test_air_filter_prompt_does_not_ask_twice_for_one_trip() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    # Prompted in the store, then a 45+ minute drive home, must stay one prompt.
    assert "state_attr('automation.buy_more_air_filters', 'last_triggered')" in block
    assert "asked_at < trigger.from_state.last_changed" in block
    assert "asked_at is none" in block


def test_air_filter_prompt_still_requires_low_inventory() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    assert "entity_id: input_number.air_filters_at_home" in block
    assert "below: 1" in block


def test_air_filter_prompt_message_has_no_stray_quote_marks() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    # The old folded scalar started and ended with a literal `"`, which the
    # push notification rendered verbatim.
    assert '"You only have' not in block


def test_restock_prompts_do_not_warn_on_overlapping_triggers() -> None:
    for path, automation_id in (
        (CLIMATE_PATH, "buy_more_air_filters"),
        (WATER_SOFTENER_PATH, "buy_more_salt"),
    ):
        block = _automation_block(path, automation_id)
        assert "mode: single" in block, automation_id
        assert "max_exceeded: silent" in block, automation_id


########################
# Salt prompt
########################


def test_salt_prompt_uses_shared_sensor() -> None:
    block = _automation_block(WATER_SOFTENER_PATH, "buy_more_salt")

    assert "binary_sensor.diy_store_visit" in block
    assert "sensor.zeke_place_place_name" not in block
    assert "sensor.tesla_place_place_name" not in block


def test_salt_prompt_has_no_arrival_backstop() -> None:
    block = _automation_block(WATER_SOFTENER_PATH, "buy_more_salt")

    # Two restock questions on a single arrival is worse than one missed bag.
    assert "binary_sensor.bayesian_zeke_home" not in block


########################
# Reply parsing parity with salt_purchased
########################


def test_air_filters_purchased_ignores_empty_or_invalid_reply_text() -> None:
    block = _automation_block(CLIMATE_PATH, "air_filters_purchased")

    assert "trigger.event.data.reply_text | int" not in block
    assert 'trigger.event.data.reply_text | default("", true) | trim' in block
    assert "purchased_text | regex_match('^\\d+$')" in block
    assert 'states("input_number.air_filters_at_home") | int(default=0)' in block
    assert "current_filters + (purchased_text | int(default=0))" in block


########################
# Behaviour of the backstop gate against real trips
########################


def _away_seconds(left: str, returned: str) -> float:
    fmt = "%Y-%m-%d %H:%M:%S"
    return (datetime.strptime(returned, fmt) - datetime.strptime(left, fmt)).total_seconds()


def _backstop_fires(left: str, returned: str) -> bool:
    return _away_seconds(left, returned) >= ERRAND_THRESHOLD_SECONDS


def test_backstop_fires_for_the_missed_home_depot_trip() -> None:
    # The trip that produced no notification: away just over three hours.
    assert _backstop_fires("2026-09-13 13:41:31", "2026-09-13 16:52:07")


def test_backstop_ignores_short_hops() -> None:
    # Sampled from the same week's presence history; none of these are errands
    # worth interrupting for.
    short_hops = [
        ("2026-09-09 11:27:14", "2026-09-09 11:27:16"),  # 2 seconds of GPS noise
        ("2026-09-12 08:17:08", "2026-09-12 08:35:20"),  # 18 minutes
        ("2026-09-12 11:21:21", "2026-09-12 11:37:36"),  # 16 minutes
        ("2026-09-14 12:31:51", "2026-09-14 13:04:56"),  # 33 minutes
    ]
    for left, returned in short_hops:
        assert not _backstop_fires(left, returned), f"{left} -> {returned}"


def test_backstop_boundary_is_inclusive() -> None:
    start = datetime(2026, 9, 13, 13, 0, 0)
    exact = start + timedelta(seconds=ERRAND_THRESHOLD_SECONDS)
    just_under = start + timedelta(seconds=ERRAND_THRESHOLD_SECONDS - 1)

    fmt = "%Y-%m-%d %H:%M:%S"
    assert _backstop_fires(start.strftime(fmt), exact.strftime(fmt))
    assert not _backstop_fires(start.strftime(fmt), just_under.strftime(fmt))


def _arrival_backstop_allowed(
    *,
    departed: str,
    returned: str,
    last_prompt: str | None,
) -> bool:
    """Mirror of the two arrival-backstop template conditions."""
    fmt = "%Y-%m-%d %H:%M:%S"
    long_enough = _backstop_fires(departed, returned)
    not_already_asked = (
        last_prompt is None
        or datetime.strptime(last_prompt, fmt) < datetime.strptime(departed, fmt)
    )
    return long_enough and not_already_asked


def test_arrival_backstop_suppressed_when_store_already_prompted() -> None:
    assert not _arrival_backstop_allowed(
        departed="2026-09-13 13:41:31",
        returned="2026-09-13 16:52:07",
        last_prompt="2026-09-13 15:10:00",
    )


def test_arrival_backstop_allowed_when_last_prompt_predates_the_trip() -> None:
    assert _arrival_backstop_allowed(
        departed="2026-09-13 13:41:31",
        returned="2026-09-13 16:52:07",
        last_prompt="2026-09-12 09:00:00",
    )


def test_arrival_backstop_allowed_when_never_prompted() -> None:
    assert _arrival_backstop_allowed(
        departed="2026-09-13 13:41:31",
        returned="2026-09-13 16:52:07",
        last_prompt=None,
    )


def _matches_diy_store(
    *,
    osm_class: str | None,
    osm_type: str,
    extratags: dict[str, str] | None = None,
    place_name: str = "unknown",
) -> bool:
    """Mirror of the three-layer match in binary_sensor.diy_store_visit."""
    diy_shop_types = {"doityourself", "hardware", "trade", "paint", "garden_centre"}
    diy_brands = [
        "home depot",
        "menards",
        "lowe's",
        "lowes",
        "fleet farm",
        "ace hardware",
        "harbor freight",
        "true value",
    ]
    extratags = extratags or {}

    is_shop = osm_class is None or osm_class == "shop"
    structured = is_shop and osm_type.lower() in diy_shop_types

    def _brand_hit(values: list[str]) -> bool:
        return any(brand in value.lower() for value in values for brand in diy_brands)

    brand = _brand_hit([extratags.get("brand", ""), extratags.get("operator", "")])
    name = _brand_hit([place_name])
    return structured or brand or name


def test_structured_tagging_matches_real_diy_stores() -> None:
    assert _matches_diy_store(osm_class="shop", osm_type="doityourself")
    assert _matches_diy_store(osm_class="shop", osm_type="hardware")
    assert _matches_diy_store(osm_class="shop", osm_type="paint")


def test_brand_tag_rescues_a_store_tagged_as_a_department_store() -> None:
    # Fleet Farm is shop=department_store, so only the brand tag can catch it.
    assert _matches_diy_store(
        osm_class="shop",
        osm_type="department_store",
        extratags={"brand": "Fleet Farm"},
    )


def test_department_stores_alone_do_not_match() -> None:
    # The same OSM type as Fleet Farm, but no DIY brand: must stay quiet.
    assert not _matches_diy_store(
        osm_class="shop",
        osm_type="department_store",
        extratags={"brand": "Target"},
        place_name="Target",
    )


def test_name_fallback_tolerates_store_numbers_and_suffixes() -> None:
    assert _matches_diy_store(
        osm_class="building",
        osm_type="retail",
        place_name="The Home Depot #2812",
    )
    assert _matches_diy_store(
        osm_class="building",
        osm_type="retail",
        place_name="Lowe's Home Improvement",
    )


def test_the_missed_sunday_geocode_still_does_not_match() -> None:
    # This is what the parking lot actually looked like. Nothing can rescue it,
    # which is why the arrive-home backstop exists.
    assert not _matches_diy_store(
        osm_class="amenity",
        osm_type="parking",
        place_name="unknown",
    )


def test_ordinary_places_do_not_match() -> None:
    assert not _matches_diy_store(osm_class="building", osm_type="house")
    assert not _matches_diy_store(
        osm_class="highway", osm_type="primary", place_name="State Highway 4"
    )
    assert not _matches_diy_store(
        osm_class="amenity", osm_type="restaurant", place_name="El Azteca Mexican Restaurant"
    )
