"""Regression tests for the DIY-store restock prompts.

Three separate failures shaped this design, all observed in production:

1. A Home Depot visit produced no prompt. Detection was exact place-name
   equality on one tracker. The arrival fix lands in the parking lot, so
   `place_name` reads `unknown` and `place_type` reads `parking`, and the
   phone then reports nothing for the rest of the visit. Real OSM names also
   carry suffixes ("The Home Depot #2812"), and the car was never watched.
2. A garden centre prompted for furnace filters, and a 30-minute timed hold
   then swallowed the real Home Depot arrival 25 minutes later.
3. Shortening that hold traded the swallow for a duplicate: a visit outlasting
   the hold re-fired for the same store.

So detection is `sensor.diy_store_current`, whose state is *which* store we are
at, held across uninformative fixes rather than on a timer. The identity is
what lets a second store prompt while a second fix for the same store does not.
An arrive-home backstop covers the case where the geocoder never names the
store at all.
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


def _template_block(name: str) -> str:
    text = ZONE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^      - name: {re.escape(name)}\n(.*?)"
        r"(?=^      - name: |^  - \w+:|^########################)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find template entity {name!r}")
    return match.group(0)


MACRO_PATH = ROOT / "custom_templates" / "diy_store.jinja"


def _macro_source() -> str:
    return MACRO_PATH.read_text(encoding="utf-8")


def _diy_store_sensor_block() -> str:
    """The matching rules, which live in the shared macro."""
    return _macro_source()


########################
# Shared detection sensor
########################


def test_both_trackers_are_watched() -> None:
    # The car has the same Places sensors as the phone and was ignored by the
    # original air-filter prompt.
    for tracker in ("zeke", "tesla"):
        _template_block(f"diy_store_{tracker}")


def test_diy_store_sensor_prefers_structured_osm_tagging() -> None:
    block = _diy_store_sensor_block()

    # The OSM key/value pair is the real category data. Read it from the
    # extended-data attributes rather than trusting a display name.
    assert "state_attr(extended, 'osm_dict')" in block
    assert "osm_class == 'shop'" in block
    # Nominatim spells the key `class` in `json` and `category` in `jsonv2`.
    # Accepting both is what keeps this working if upstream switches format.
    assert "osm.get('class') or osm.get('category')" in block


def _macro_code() -> str:
    """Macro source with Jinja comments stripped, so prose is not asserted on."""
    return re.sub(r"\{#.*?#\}", "", _macro_source(), flags=re.DOTALL)


def test_diy_store_sensor_does_not_use_the_dead_category_sensor() -> None:
    code = _macro_code()

    # sensor.<tracker>_place_place_category reads osm_dict["category"], but
    # Nominatim's reverse endpoint returns that key as "class". The sensor has
    # been `unknown` on both trackers for the whole recorder window, so it must
    # never be read - only explained in the comments.
    assert "_place_place_category" not in code
    assert "_place_place_type" in code, "the live type sensor is still the fallback"


def test_diy_store_sensor_structural_types_stock_filters_and_salt() -> None:
    block = _diy_store_sensor_block()
    types_line = block[block.index("set diy_shop_types") : block.index("set diy_brands")]

    for shop_type in ("doityourself", "hardware", "trade"):
        assert shop_type in types_line, f"missing shop type {shop_type!r}"

    # shop=department_store is Target as well as Fleet Farm, so it must not be a
    # structural match; Fleet Farm comes in via its brand tag instead.
    # shop=garden_centre prompted for furnace filters at a garden centre on
    # 2026-09-20, and shop=paint has the same problem: neither stocks filters
    # or softener salt.
    for shop_type in ("department_store", "garden_centre", "paint"):
        assert shop_type not in types_line, f"{shop_type!r} must not match structurally"


def test_diy_store_sensor_does_not_use_a_timed_hold() -> None:
    block = _diy_store_sensor_block()

    # A timed hold cannot tell "still in this store" from "now at the next
    # store". Long enough to cover a visit swallows the next store; short
    # enough to re-arm re-fires for the same one. Both were observed.
    assert "delay_off" not in block


def test_store_identity_is_canonical() -> None:
    src = _macro_source()

    # The same store reached through different metadata must produce the same
    # string, or the prompts read it as a new store. A known brand collapses to
    # its own token; everything else collapses to shop:<type>. Raw place names
    # are never used as the identity.
    assert "brands_found[0]" in src
    assert "'shop:' ~ place_type" in src
    assert "select('in', haystack)" in src
    haystack = src[src.index("set haystack") : src.index("brands_found")]
    for field in ("brand", "operator", "_place_place_name", "_place_zone_name"):
        assert field in haystack, f"{field} must feed canonicalisation"


def test_hold_is_per_tracker_not_combined() -> None:
    zeke = _template_block("diy_store_zeke")
    tesla = _template_block("diy_store_tesla")

    # Trackers move independently. Deciding the hold from all of them at once
    # fails both ways: "any clears" lets a car at home cancel the phone's
    # visit, "every clears" lets a car parked in a lot pin the last store
    # forever. Each tracker holds only its own state.
    for block, tracker in ((zeke, "zeke"), (tesla, "tesla")):
        assert f"diy_store_identity('{tracker}')" in block
        assert f"diy_place_is_vague('{tracker}')" in block
        assert "this.state" in block
        for other in {"zeke", "tesla"} - {tracker}:
            assert other not in block, f"{tracker} sensor must not read {other}"


def test_combined_sensor_collapses_trackers_to_one_identity() -> None:
    block = _template_block("diy_store_current")

    # Two trackers arriving together must not race into two prompts.
    assert "sensor.diy_store_zeke" in block
    assert "sensor.diy_store_tesla" in block
    assert "reject('in', ['none', 'unknown', 'unavailable'])" in block


def test_holds_through_uninformative_fixes_but_not_on_a_timer() -> None:
    src = _macro_source()

    # parking/unknown is the lot, not evidence of having left.
    assert "'parking'" in src
    assert "diy_place_is_vague" in src
    for block in (_template_block("diy_store_zeke"), _template_block("diy_store_tesla")):
        assert "delay_off" not in block


def test_vagueness_ignores_zone_name() -> None:
    src = _macro_source()
    vague_macro = src[src.index("macro diy_place_is_vague") :]

    # zone_name reads "not_home" when away, so it is never vague. Letting it
    # count as evidence would make the hold unreachable.
    assert "place_zone_name" not in vague_macro
    assert "place_place_name" in vague_macro


def test_diy_store_binary_companion_derives_from_the_identity() -> None:
    block = _template_block("diy_store_visit")

    assert "states('sensor.diy_store_current')" in block
    assert "'none', 'unknown', 'unavailable'" in block


def test_prompts_trigger_on_the_identity_not_the_boolean() -> None:
    for path, automation_id in (
        (CLIMATE_PATH, "buy_more_air_filters"),
        (WATER_SOFTENER_PATH, "buy_more_salt"),
    ):
        block = _automation_block(path, automation_id)
        assert "entity_id: sensor.diy_store_current" in block, automation_id
        assert "binary_sensor.diy_store_visit" not in block, automation_id
        assert "trigger.to_state.state != trigger.from_state.state" in block, automation_id
        assert "'none', 'unknown', 'unavailable'" in block, automation_id


def test_diy_store_sensor_reads_brand_tags() -> None:
    block = _diy_store_sensor_block()

    # brand/operator are curated OSM tags, not display names, so they are a
    # better fallback than place_name for stores tagged as something generic.
    assert "extratags.get('brand', '')" in block
    assert "extratags.get('operator', '')" in block


def test_diy_store_sensor_keeps_a_name_fallback() -> None:
    src = _macro_source()

    # Substring search, not equality, so "The Home Depot #2812" still matches.
    assert "select('in', haystack)" in src
    assert "| map('lower')" in src
    for brand in ("home depot", "menards", "lowes", "fleet farm", "ace hardware"):
        assert brand in src, f"missing store keyword {brand!r}"


def test_diy_store_sensor_name_fallback_has_no_generic_tokens() -> None:
    src = _macro_source()

    brand_list = src[src.index("set diy_brands") : src.index("set extended")]
    # A bare "hardware" substring would match on name alone; shop=hardware
    # already covers it structurally.
    assert "'hardware'" not in brand_list


def test_diy_store_sensor_degrades_without_extended_attributes() -> None:
    block = _diy_store_sensor_block()

    # If the integration's extended attributes are ever turned off, osm_dict is
    # empty and the plain place_type sensor has to carry the structured check.
    assert "states('sensor.' ~ tracker ~ '_place_place_type')" in block
    assert "osm_class is none" in block


def test_diy_store_sensor_also_reads_zone_names() -> None:
    block = _diy_store_sensor_block()

    # Reading zone_name means store zones, if any are ever added, are picked up
    # by the same keyword list with no further wiring.
    assert "_place_zone_name" in block


########################
# Air filter prompt
########################


def test_air_filter_prompt_uses_shared_sensor_not_place_strings() -> None:
    block = _automation_block(CLIMATE_PATH, "buy_more_air_filters")

    assert "sensor.diy_store_current" in block
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

    assert "sensor.diy_store_current" in block
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


DIY_SHOP_TYPES = {"doityourself", "hardware", "trade"}
# Punctuationless, matching the macro: the haystack is stripped to suit.
DIY_BRANDS = [
    "home depot",
    "menards",
    "lowes",
    "fleet farm",
    "ace hardware",
    "harbor freight",
    "true value",
]


def _canonical_identity(
    *,
    osm_class: str | None,
    osm_type: str,
    extratags: dict[str, str] | None = None,
    place_name: str = "unknown",
    zone_name: str = "not_home",
) -> str:
    """Mirror of diy_store_identity(): the store's canonical id, or ""."""
    extratags = extratags or {}
    haystack = " | ".join(
        value.lower()
        for value in (
            extratags.get("brand", ""),
            extratags.get("operator", ""),
            place_name,
            zone_name,
        )
    ).replace("'", "").replace("\u2019", "")
    for brand in DIY_BRANDS:
        if brand in haystack:
            return brand
    is_shop = osm_class is None or osm_class == "shop"
    if is_shop and osm_type.lower() in DIY_SHOP_TYPES:
        return f"shop:{osm_type.lower()}"
    return ""


def _matches_diy_store(**kwargs: object) -> bool:
    return bool(_canonical_identity(**kwargs))  # type: ignore[arg-type]


def test_same_store_through_different_metadata_has_one_identity() -> None:
    # The geocoder reaches the same store different ways between fixes. If the
    # identity changed with it, each variation would read as a new store and
    # prompt again during a single visit.
    variations = [
        _canonical_identity(
            osm_class="shop", osm_type="doityourself", extratags={"brand": "The Home Depot"}
        ),
        _canonical_identity(osm_class="shop", osm_type="doityourself", place_name="The Home Depot"),
        _canonical_identity(
            osm_class="shop", osm_type="doityourself", place_name="The Home Depot #2812"
        ),
        _canonical_identity(
            osm_class="shop", osm_type="doityourself", extratags={"operator": "Home Depot USA"}
        ),
        _canonical_identity(osm_class="building", osm_type="retail", place_name="THE HOME DEPOT"),
    ]

    assert set(variations) == {"home depot"}, variations


def test_unbranded_store_identity_is_a_stable_type_key() -> None:
    # No brand to latch onto, so the type carries the identity. It must not be
    # the raw place name, which varies between fixes.
    assert (
        _canonical_identity(osm_class="shop", osm_type="hardware", place_name="Smith Hardware Co")
        == "shop:hardware"
    )
    assert (
        _canonical_identity(osm_class="shop", osm_type="hardware", place_name="unknown")
        == "shop:hardware"
    )


def test_structured_tagging_matches_real_diy_stores() -> None:
    assert _matches_diy_store(osm_class="shop", osm_type="doityourself")
    assert _matches_diy_store(osm_class="shop", osm_type="hardware")
    assert _matches_diy_store(osm_class="shop", osm_type="trade")


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


########################
# The 2026-09-20 double failure
########################


def test_garden_centre_no_longer_prompts_for_air_filters() -> None:
    # Bachman's: shop=garden_centre, no DIY brand. Prompted at 14:35 that day.
    assert not _matches_diy_store(
        osm_class="shop",
        osm_type="garden_centre",
        place_name="Bachman's",
    )


def test_paint_shops_no_longer_match() -> None:
    assert not _matches_diy_store(osm_class="shop", osm_type="paint")


def test_the_home_depot_arrival_that_was_swallowed_still_matches() -> None:
    # The geocode was perfect that day; only the hold from the earlier false
    # positive stopped the automation seeing an edge.
    assert _matches_diy_store(
        osm_class="shop",
        osm_type="doityourself",
        place_name="The Home Depot",
    )


def test_other_errands_from_that_trip_do_not_match() -> None:
    same_trip = [
        ("shop", "supermarket", "Valley Foods"),
        ("amenity", "dentist", "Crestridge Dental"),
        ("shop", "craft", "Michaels"),
        ("shop", "games", "Games by James"),
        ("shop", "supermarket", "Bodega 42 Fresh Market"),
        ("amenity", "parking", "unknown"),
    ]
    for osm_class, osm_type, place_name in same_trip:
        assert not _matches_diy_store(
            osm_class=osm_class, osm_type=osm_type, place_name=place_name
        ), f"{place_name} ({osm_class}={osm_type}) must not match"


########################
# The hold, replayed against real fixes
########################

VAGUE = {"", "none", "unknown", "unavailable", "parking"}

TRACKERS = ("zeke", "tesla")

# A fix is (place_name, place_type) for one tracker. A sample is one fix per
# tracker, in (phone, car) order. Modelling a single tracker is what let the
# independent-tracker bugs through review twice.
Fix = tuple[str, str]
Sample = tuple[Fix, Fix]


def _tracker_identity(previous: str, fix: Fix) -> str:
    """Mirror of one sensor.diy_store_<tracker>."""
    place_name, place_type = fix
    matched = _canonical_identity(
        osm_class="shop" if place_type not in VAGUE else None,
        osm_type=place_type,
        place_name=place_name,
    )
    if matched:
        return matched
    vague = place_type in VAGUE and place_name.lower() in VAGUE
    return previous if vague else "none"


def _replay(samples: list[Sample]) -> tuple[list[str], int]:
    """Return sensor.diy_store_current after each sample, and prompts sent."""
    per_tracker = dict.fromkeys(TRACKERS, "none")
    states: list[str] = []
    combined_prev = "none"
    prompts = 0
    for sample in samples:
        fresh: list[str] = []
        for tracker, fix in zip(TRACKERS, sample):
            place_name, place_type = fix
            matched = _canonical_identity(
                osm_class="shop" if place_type not in VAGUE else None,
                osm_type=place_type,
                place_name=place_name,
            )
            if matched:
                fresh.append(matched)
            per_tracker[tracker] = _tracker_identity(per_tracker[tracker], fix)
        held = [per_tracker[t] for t in TRACKERS if per_tracker[t] not in VAGUE]
        # Only a fresh detection may change which store is reported. A hold can
        # sustain the current one; it can never substitute another, or a trip
        # oscillates between two trackers' holds and prompts again each time.
        if fresh:
            combined = fresh[0]
        elif combined_prev != "none" and combined_prev in held:
            combined = combined_prev
        else:
            combined = "none"
        if combined not in VAGUE and combined != combined_prev:
            prompts += 1
        states.append(combined)
        combined_prev = combined
    return states, prompts


def _both(place_name: str, place_type: str) -> Sample:
    """Phone and car together, the common case."""
    return ((place_name, place_type), (place_name, place_type))


HOME: Fix = ("unknown", "house")
LOT: Fix = ("unknown", "parking")
HOME_DEPOT: Fix = ("The Home Depot", "doityourself")
ROAD: Fix = ("Cedar Avenue", "motorway")


def test_replay_of_the_2026_09_20_trip_prompts_exactly_once() -> None:
    trip = [
        _both("unknown", "secondary"),
        _both("Valley Foods", "supermarket"),
        _both("Crestridge Dental", "dentist"),
        _both("Michaels", "craft"),
        _both(*LOT),
        _both("unknown", "house"),
        _both("Games by James", "games"),
        _both("County Road 42 West", "trunk"),
        _both("Bachman's", "garden_centre"),
        _both("Pennock Lane", "tertiary"),
        _both("Bodega 42 Fresh Market", "supermarket"),
        _both(*LOT),
        _both(*HOME_DEPOT),
        _both(*LOT),
        _both(*LOT),
        _both("unknown", "house"),
    ]
    states, prompts = _replay(trip)

    assert prompts == 1, "the Home Depot arrival, and nothing else"
    assert states[12] == "home depot"
    assert states[8] == "none", "the garden centre must not match"
    assert states[-1] == "none", "driving home must re-arm for next time"


def test_a_long_visit_does_not_reprompt() -> None:
    # Arrive, sit in the lot far longer than any timed hold would survive, then
    # a second store fix on the way out.
    states, prompts = _replay(
        [_both(*LOT), _both(*HOME_DEPOT)]
        + [_both(*LOT)] * 20
        + [_both(*HOME_DEPOT), _both("County Road 42", "trunk")]
    )

    assert prompts == 1
    assert states[-1] == "none"


def test_two_stores_in_one_trip_prompt_twice() -> None:
    _, prompts = _replay(
        [
            _both("Ace Hardware", "hardware"),
            _both(*LOT),
            _both("County Road 42", "trunk"),
            _both(*LOT),
            _both(*HOME_DEPOT),
        ]
    )

    assert prompts == 2


def test_adjacent_stores_prompt_twice_without_an_intervening_road_fix() -> None:
    # Places can go straight from one store to the next through a single vague
    # sample. A boolean sensor holds `on` across that and loses the second
    # store; the identity changes, so the prompt still fires.
    states, prompts = _replay(
        [
            _both("Ace Hardware", "hardware"),
            _both(*LOT),
            _both(*HOME_DEPOT),
        ]
    )

    assert states == ["ace hardware", "ace hardware", "home depot"]
    assert prompts == 2


def test_a_parked_car_elsewhere_does_not_break_the_hold() -> None:
    # The trip is made without the Tesla, which sits at home reporting `house`
    # the whole time. Its stale evidence must not clear a visit the phone
    # established, or the next phone fix re-prompts for the same store.
    states, prompts = _replay(
        [
            (HOME, HOME),
            (HOME_DEPOT, HOME),
            (LOT, HOME),
            (LOT, HOME),
            (HOME_DEPOT, HOME),
            (("Cedar Avenue", "motorway"), HOME),
        ]
    )

    assert prompts == 1, "one visit, one prompt, despite the car sitting at home"
    assert states[2:5] == ["home depot"] * 3, "the hold must survive"
    assert states[-1] == "none"


def test_either_tracker_can_establish_the_visit() -> None:
    _, prompts = _replay([(HOME, HOME), (HOME, HOME_DEPOT)])

    assert prompts == 1


def test_hold_does_not_survive_arriving_home() -> None:
    states, _ = _replay([_both(*HOME_DEPOT), _both("unknown", "house")])

    assert states == ["home depot", "none"]


def test_an_idle_vague_tracker_does_not_block_re_arming() -> None:
    # The car is left in a generic lot and reports `parking` indefinitely, so
    # it is never "informative". Requiring every tracker to agree before
    # clearing pinned the last store forever and a later visit to it could
    # never trigger. Each tracker holding only its own state fixes that: the
    # car holds its own "none", and the phone clears on its own road fix.
    states, prompts = _replay(
        [
            (HOME, HOME),
            (HOME_DEPOT, LOT),
            (LOT, LOT),
            (ROAD, LOT),
            (HOME, LOT),
            (HOME_DEPOT, LOT),
        ]
    )

    assert states[3] == "none", "the phone's road fix must clear the visit"
    assert prompts == 2, "the second visit to the same store must prompt again"


def test_an_unavailable_tracker_does_not_block_re_arming() -> None:
    dead: Fix = ("unavailable", "unavailable")
    states, prompts = _replay(
        [(HOME, dead), (HOME_DEPOT, dead), (LOT, dead), (ROAD, dead), (HOME_DEPOT, dead)]
    )

    assert states[3] == "none"
    assert prompts == 2


def test_a_car_left_in_a_store_lot_still_clears_once_it_moves() -> None:
    # The one case the per-tracker hold cannot shortcut: the car is parked at
    # the store itself, so it legitimately still looks like it is there. It
    # clears as soon as the car produces a road fix.
    states, _ = _replay(
        [(HOME_DEPOT, HOME_DEPOT), (ROAD, LOT), (HOME, LOT), (HOME, ROAD), (HOME, HOME)]
    )

    assert states[2] == "home depot", "the car is still at the store"
    assert states[-1] == "none", "and clears once the car drives off"


########################
# Identity aliasing and stale-vs-fresh selection
########################


def test_lowes_spellings_are_one_identity() -> None:
    # The geocoder can alternate between a punctuation-bearing brand tag and a
    # punctuationless place name inside one visit. Two tokens would read as two
    # stores and prompt twice.
    spellings = [
        _canonical_identity(
            osm_class="shop", osm_type="doityourself", extratags={"brand": "Lowe's"}
        ),
        _canonical_identity(osm_class="shop", osm_type="doityourself", place_name="Lowes"),
        _canonical_identity(
            osm_class="shop", osm_type="doityourself", place_name="Lowe's Home Improvement"
        ),
        _canonical_identity(
            osm_class="shop", osm_type="doityourself", place_name="Lowe’s Home Improvement"
        ),
    ]

    assert set(spellings) == {"lowes"}, spellings


def test_brand_tokens_carry_no_punctuation() -> None:
    src = _macro_code()
    brand_list = src[src.index("set diy_brands") : src.index("set extended")]

    assert "'" not in brand_list.replace("'home depot'", "").replace("'menards'", "").replace(
        "'lowes'", ""
    ).replace("'fleet farm'", "").replace("'ace hardware'", "").replace(
        "'harbor freight'", ""
    ).replace("'true value'", ""), "brand tokens must be punctuationless"
    assert "replace(\"'\", '')" in src, "the haystack must be stripped to match"


def test_alternating_lowes_spellings_prompt_once() -> None:
    _, prompts = _replay(
        [
            _both("unknown", "house"),
            _both("Lowe's Home Improvement", "doityourself"),
            _both("Lowes", "doityourself"),
            _both(*LOT),
            _both("Lowe’s", "doityourself"),
            _both("Cedar Avenue", "motorway"),
        ]
    )

    assert prompts == 1


def test_a_new_store_on_one_tracker_beats_a_held_one_on_the_other() -> None:
    # The phone establishes Ace Hardware, then sits on vague fixes holding it,
    # while the car resolves to Home Depot. Taking the first non-none in
    # tracker order would keep reporting the stale Ace and never hand the
    # prompts their transition.
    ace: Fix = ("Ace Hardware", "hardware")
    states, prompts = _replay(
        [
            (HOME, HOME),
            (ace, LOT),
            (LOT, LOT),
            (LOT, HOME_DEPOT),
        ]
    )

    assert states[1] == "ace hardware"
    assert states[2] == "ace hardware", "the hold still covers a quiet phone"
    assert states[3] == "home depot", "a freshly detected store must win"
    assert prompts == 2


def test_a_held_identity_is_still_the_fallback() -> None:
    # Fresh-beats-held must not undo the hold: with nothing detected on this
    # fix, the held identity is what keeps one visit to one prompt.
    states, prompts = _replay([_both(*HOME_DEPOT)] + [_both(*LOT)] * 5)

    assert states == ["home depot"] * 6
    assert prompts == 1


########################
# Only a fresh detection may change which store is reported
########################


ACE: Fix = ("Ace Hardware", "hardware")


def test_a_held_identity_never_substitutes_for_another() -> None:
    # The phone holds Ace while the car newly detects Home Depot, then the car
    # goes vague too. With both trackers holding, picking by tracker order sent
    # ace -> home depot -> ace and a third prompt for one trip.
    states, prompts = _replay(
        [
            (HOME, HOME),
            (ACE, LOT),
            (LOT, HOME_DEPOT),
            (LOT, LOT),
            (LOT, LOT),
        ]
    )

    assert states == ["none", "ace hardware", "home depot", "home depot", "home depot"]
    assert prompts == 2, "one per store, not one per flip between holds"


def test_losing_support_goes_quiet_rather_than_to_another_hold() -> None:
    # The car drives off and clears while the phone is still holding Ace.
    # Adopting the phone's hold would be a store change with no new arrival
    # behind it, so the sensor goes to none instead.
    states, prompts = _replay(
        [
            (ACE, LOT),
            (LOT, HOME_DEPOT),
            (LOT, ("Cedar Avenue", "motorway")),
        ]
    )

    assert states == ["ace hardware", "home depot", "none"]
    assert prompts == 2


def test_going_quiet_does_not_strand_a_tracker_still_at_a_store() -> None:
    # Cheap to fall to none: the next informative fix from a tracker that
    # really is at the store matches again and prompts.
    states, prompts = _replay(
        [(ACE, LOT), (LOT, HOME_DEPOT), (LOT, ROAD), (ACE, ROAD)]
    )

    assert states[2] == "none"
    assert states[3] == "ace hardware"
    assert prompts == 3, "ace, home depot, then ace freshly re-detected"


def test_every_prompt_is_backed_by_a_fresh_detection() -> None:
    # The invariant, checked over a long mixed trip: the identity only ever
    # changes to a store on a sample where some tracker actually matched.
    trip: list[Sample] = [
        (HOME, HOME),
        (ACE, ACE),
        (LOT, LOT),
        (LOT, HOME_DEPOT),
        (LOT, LOT),
        (ROAD, LOT),
        (HOME_DEPOT, LOT),
        (LOT, LOT),
        (ROAD, ROAD),
        (HOME, HOME),
    ]
    states, _ = _replay(trip)

    previous = "none"
    for sample, state in zip(trip, states):
        if state != previous and state != "none":
            matched_now = any(
                _canonical_identity(
                    osm_class="shop" if place_type not in VAGUE else None,
                    osm_type=place_type,
                    place_name=place_name,
                )
                for place_name, place_type in sample
            )
            assert matched_now, f"{previous} -> {state} with no fresh detection"
        previous = state
