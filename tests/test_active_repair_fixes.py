from pathlib import Path

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def template_entity(path: Path, unique_id: str) -> dict:
    class PackageLoader(yaml.SafeLoader):
        pass

    PackageLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
    config = yaml.load(path.read_text(), Loader=PackageLoader)
    return next(
        entity
        for block in config["template"]
        for entities in block.values()
        if isinstance(entities, list)
        for entity in entities
        if entity.get("unique_id") == unique_id
    )


def test_unmonitored_dishwasher_remains_unavailable_without_deleted_source() -> None:
    entity = template_entity(ROOT / "packages/cleaning.yaml", "dishwasher_running")
    env = NativeEnvironment(undefined=StrictUndefined)
    # Rendering needs no state lookup at all; absent monitoring must never
    # masquerade as an idle dishwasher or keep a dangling entity reference.
    assert env.from_string(entity["availability"]).render() is False
    assert env.from_string(entity["state"]).render() is False
    assert entity["delay_on"] == "0:05:00"
    assert entity["delay_off"] == "0:10:00"


@pytest.mark.parametrize(
    "bathroom,baseline,available,delta",
    [(65, 55, True, 10), (55, 56, True, -1), ("unavailable", 55, False, None),
     (65, "unavailable", False, None), (65, "unknown", False, None)],
)
def test_basement_delta_uses_real_ambient_source_and_fails_closed(
    bathroom, baseline, available, delta
) -> None:
    entity = template_entity(ROOT / "packages/climate.yaml", "basement_bathroom_humidity_delta")
    values = {
        "sensor.basement_bathroom_tph_humidity": bathroom,
        "sensor.basement_dehumidifier_humidity": baseline,
    }
    env = NativeEnvironment(undefined=StrictUndefined)
    env.globals.update(
        states=lambda entity_id: str(values[entity_id]),
        has_value=lambda entity_id: values[entity_id] not in ("unknown", "unavailable"),
    )
    assert env.from_string(entity["availability"]).render() is available
    if available:
        assert env.from_string(entity["state"]).render() == delta


def test_dashboard_resources_use_marketplace_paths_without_changing_query_versions() -> None:
    text = (ROOT / "configuration.yaml").read_text()
    assert "/hacsfiles/" not in text
    assert "/local/community/lovelace-navbar-card/navbar-card.js?v=1.8.0" in text
    assert "/local/community/lovelace-card-mod/card-mod.js" in text
