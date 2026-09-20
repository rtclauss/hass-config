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


def _diy_store_sensor_block() -> str:
    return _template_block("diy_store_current")


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
    assert "osm_class == 'shop'" in block
    # Nominatim spells the key `class` in `json` and `category` in `jsonv2`.
    # Accepting both is what keeps this working if upstream switches format.
    assert "osm.get('class') or osm.get('category')" in block


def test_diy_store_sensor_does_not_use_the_dead_category_sensor() -> None:
    block = _diy_store_sensor_block()

    # sensor.<tracker>_place_place_category reads osm_dict["category"], but
    # Nominatim's reverse endpoint returns that key as "class". The sensor has
    # been `unknown` on both trackers for the whole recorder window.
    assert "_place_place_category" not in block


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


def test_diy_store_sensor_state_is_the_store_identity() -> None:
    block = _diy_store_sensor_block()

    # A boolean cannot tell "another fix for the store I am in" from "a
    # different store". The state carries the identity so the consumers can.
    assert "ns.store" in block
    assert "brand_hit[0]" in block
    assert "'shop:' ~ place_type" in block
    assert "none" in block


def test_diy_store_sensor_holds_through_uninformative_fixes() -> None:
    block = _diy_store_sensor_block()

    # parking/unknown is the lot, not evidence of having left.
    assert "'parking'" in block
    assert "ns.all_informative" in block
    assert "this.state if this is defined" in block


def test_diy_store_clear_requires_every_tracker_to_agree() -> None:
    block = _diy_store_sensor_block()

    # Trackers move independently: a Tesla parked at home reports `house`
    # forever. If one tracker's stale evidence could clear a visit another
    # tracker established, the hold would drop and the next fix would
    # re-prompt. Clearing is therefore all-trackers, not any-tracker.
    assert "namespace(store='', all_informative=true)" in block
    clear = block[block.index("elif place_type in vague") :]
    clear = clear[: clear.index("endif")]
    assert "all_informative = false" in clear
    assert "place_name in vague" in clear


def test_diy_store_sensor_does_not_let_zone_name_decide_evidence() -> None:
    block = _diy_store_sensor_block()

    # zone_name reads "not_home" when away, so it is never vague. Letting it
    # count as evidence would make the hold unreachable.
    clear = block[block.index("elif place_type in vague") :]
    clear = clear[: clear.index("endif")]
    assert "zone_name" not in clear


def test_diy_store_binary_companion_derives_from_the_identity() -> None:
    block = _template_block("diy_store_visit")

    # Nothing triggers off the boolean; it exists for dashboards.
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
        # An unqualified state trigger also fires on attribute-only changes and
        # on the way back to "none"; both must be filtered out.
        assert "trigger.to_state.state != trigger.from_state.state" in block, automation_id
        assert "'none', 'unknown', 'unavailable'" in block, automation_id


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


def _matches_diy_store(
    *,
    osm_class: str | None,
    osm_type: str,
    extratags: dict[str, str] | None = None,
    place_name: str = "unknown",
) -> bool:
    """Mirror of the three-layer match in sensor.diy_store_current."""
    diy_shop_types = {"doityourself", "hardware", "trade"}
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

# A fix is (place_name, place_type) for one tracker. A sample is one fix per
# tracker, in (phone, car) order — modelling only one tracker is what let the
# independent-tracker bug through review the first time.
Fix = tuple[str, str]
Sample = tuple[Fix, Fix]


def _identity(previous: str, sample: Sample) -> str:
    """Mirror of sensor.diy_store_current over one sample."""
    store = ""
    all_informative = True
    for place_name, place_type in sample:
        matched = _matches_diy_store(
            osm_class="shop" if place_type not in VAGUE else None,
            osm_type=place_type,
            place_name=place_name,
        )
        if matched and not store:
            store = (
                place_name.lower()
                if place_name.lower() not in VAGUE
                else f"shop:{place_type}"
            )
        elif place_type in VAGUE and place_name.lower() in VAGUE:
            all_informative = False
    if store:
        return store
    return "none" if all_informative else previous


def _replay(samples: list[Sample]) -> tuple[list[str], int]:
    """Return the identity after each sample and the number of prompts sent."""
    states: list[str] = []
    prev = "none"
    prompts = 0
    for sample in samples:
        new = _identity(prev, sample)
        if new not in VAGUE and new != prev:
            prompts += 1
        states.append(new)
        prev = new
    return states, prompts


def _both(place_name: str, place_type: str) -> Sample:
    """Phone and car together, the common case."""
    return ((place_name, place_type), (place_name, place_type))


HOME: Fix = ("unknown", "house")
LOT: Fix = ("unknown", "parking")
HOME_DEPOT: Fix = ("The Home Depot", "doityourself")


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
    assert states[12] == "the home depot"
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

    assert states == ["ace hardware", "ace hardware", "the home depot"]
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
    assert states[2:5] == ["the home depot"] * 3, "the hold must survive"
    assert states[-1] == "none"


def test_either_tracker_can_establish_the_visit() -> None:
    _, prompts = _replay([(HOME, HOME), (HOME, HOME_DEPOT)])

    assert prompts == 1


def test_hold_does_not_survive_arriving_home() -> None:
    states, _ = _replay([_both(*HOME_DEPOT), _both("unknown", "house")])

    assert states == ["the home depot", "none"]
