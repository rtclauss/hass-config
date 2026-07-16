from __future__ import annotations

import json
from copy import deepcopy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ha_label_assignments import (  # noqa: E402
    audit_assignments,
    build_reference_graph,
    discover_repository_inventory,
    load_assignment_manifest,
    plan_assignment_operations,
    plan_retired_label_deletions,
    rule_matches,
    validate_assignment_manifest,
)
from scripts.ha_label_taxonomy import (  # noqa: E402
    load_label_specs,
    main as taxonomy_main,
    normalize_live_export,
)

ASSIGNMENTS_PATH = ROOT / "docs" / "ha_label_assignments.json"
TAXONOMY_PATH = ROOT / "docs" / "ha_label_taxonomy.yaml"
LIVE_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "ha_label_live_export.json"


def _manifest() -> dict:
    return load_assignment_manifest(ASSIGNMENTS_PATH)


def _live_fixture() -> dict:
    return normalize_live_export(json.loads(LIVE_FIXTURE_PATH.read_text(encoding="utf-8")))


def _complete_live_fixture(manifest: dict) -> dict:
    live = deepcopy(_live_fixture())
    areas_by_id = {area["area_id"]: area for area in live["areas"]}
    for area_id in manifest["area_assignments"]:
        areas_by_id.setdefault(area_id, {"area_id": area_id, "labels": []})
    live["areas"] = list(areas_by_id.values())

    entities_by_id = {entity["entity_id"]: entity for entity in live["entities"]}
    for item in manifest["behaviors"] + manifest["helpers"]:
        entities_by_id.setdefault(
            item["entity_id"],
            {"entity_id": item["entity_id"], "labels": []},
        )
    live["entities"] = list(entities_by_id.values())
    return live


def test_taxonomy_has_33_active_labels_and_only_documented_retirements() -> None:
    specs = load_label_specs(TAXONOMY_PATH)
    active = {spec.label_id for spec in specs if spec.lifecycle == "active"}
    deprecated = {spec.label_id for spec in specs if spec.lifecycle == "deprecated"}
    manifest = _manifest()

    assert len(active) == 33
    assert active == set(manifest["managed_labels"])
    assert deprecated == set(manifest["retired_labels"])


def test_assignment_manifest_is_valid_and_covers_repository_inventory() -> None:
    specs = load_label_specs(TAXONOMY_PATH)
    active = {spec.label_id for spec in specs if spec.lifecycle == "active"}
    manifest = _manifest()

    assert validate_assignment_manifest(manifest, active_label_ids=active) == []
    assert manifest["metadata"]["repository_counts"] == {
        "automation": 231,
        "script": 139,
        "scene": 34,
        "helper": 104,
    }
    assert manifest["metadata"]["live_only_counts"] == {
        "automation": 31,
        "script": 3,
    }


def test_every_behavior_and_helper_has_explicit_labels() -> None:
    manifest = _manifest()

    assert all(item["labels"] for item in manifest["behaviors"])
    assert all(item["labels"] for item in manifest["helpers"])
    assert sum(item["source"] == "repository" for item in manifest["behaviors"]) == 404
    assert sum(item["source"] == "live_only" for item in manifest["behaviors"]) == 34
    assert len({item["entity_id"] for item in manifest["helpers"]}) == 104


def test_all_scenes_have_unique_stable_ids_without_entity_id_changes() -> None:
    inventory = discover_repository_inventory()
    scenes = [item for item in inventory["behaviors"] if item["kind"] == "scene"]
    manifest_scenes = {
        item["unique_id"]: item["entity_id"]
        for item in _manifest()["behaviors"]
        if item["kind"] == "scene" and item["source"] == "repository"
    }

    assert len(scenes) == 34
    assert len({item["unique_id"] for item in scenes}) == 34
    assert {item["unique_id"]: item["entity_id"] for item in scenes} == manifest_scenes


def test_reference_graph_covers_all_repository_behaviors() -> None:
    graph = build_reference_graph()

    assert graph["node_count"] == 404
    assert graph["edge_count"] > 300
    assert "automation.alarm_wake_up" in graph["graph"]
    assert "script.wake_up_script" in graph["graph"]["automation.alarm_wake_up"]


def test_rules_support_integration_domain_and_manufacturer_matching() -> None:
    manifest = _manifest()
    rules = {rule["id"]: rule for rule in manifest["rules"]}

    assert rule_matches(
        rules["connectivity_platforms"],
        {"entity_id": "sensor.example", "platform": "mqtt"},
        "entity",
    )
    assert rule_matches(
        rules["inovelli_devices"],
        {"id": "device", "manufacturer": "Inovelli"},
        "device",
    )
    assert not rule_matches(
        rules["inovelli_devices"],
        {"id": "device", "manufacturer": "Sonos"},
        "device",
    )


def test_fixture_assignments_preserve_unmanaged_labels_and_migrate_retired_labels() -> None:
    operations = plan_assignment_operations(_manifest(), _live_fixture())
    by_object = {(item["registry"], item["object_id"]): item for item in operations}

    alarm = by_object[("entity", "automation.alarm_wake_up")]
    assert "unmanaged_personal" in alarm["after"]
    assert "sleep" not in alarm["after"]
    assert "wake_up_scope" in alarm["after"]
    assert "sleep_sensitive" in alarm["after"]

    hallway = by_object.get(("area", "hallway"))
    assert hallway is None  # Already has hallway plus an unmanaged label.


def test_extension_labels_resolve_to_at_least_six_fixture_objects() -> None:
    manifest = _manifest()
    audit = audit_assignments(manifest, _live_fixture())

    assert audit["extension_threshold_failures"] == {}
    assert audit["coverage_by_domain"]["automation"]["fully_assigned_live"] == 0
    assert audit["coverage_by_domain"]["automation"]["planned_labeled"] == 1
    assert all(
        audit["extension_counts"][label] >= manifest["minimum_items_for_extension"]
        for label in manifest["extension_labels"]
    )


def test_audit_reports_missing_desired_registry_objects() -> None:
    manifest = deepcopy(_manifest())
    live = _complete_live_fixture(manifest)
    manifest["area_assignments"]["missing_area"] = ["privacy_sensitive"]
    live["entities"] = [
        entity
        for entity in live["entities"]
        if entity["entity_id"] != "scene.arrive_home"
    ]
    mqtt_entity = next(
        entity
        for entity in live["entities"]
        if entity["entity_id"] == "sensor.mqtt_0"
    )
    mqtt_entity["device_id"] = "missing_device"

    audit = audit_assignments(manifest, live)

    assert audit["missing_registry_objects"] == {
        "area": ["missing_area"],
        "device": ["missing_device"],
        "entity": ["scene.arrive_home"],
    }


def test_apply_refuses_to_skip_missing_registry_objects(
    tmp_path: Path,
    capsys,
) -> None:
    manifest = deepcopy(_manifest())
    live = _complete_live_fixture(manifest)
    manifest["area_assignments"]["missing_area"] = ["privacy_sensitive"]
    manifest_path = tmp_path / "assignments.json"
    live_path = tmp_path / "live.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    live_path.write_text(json.dumps(live), encoding="utf-8")

    result = taxonomy_main(
        [
            "--assignments",
            str(manifest_path),
            "apply-assignments",
            "--live-json",
            str(live_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert result == 1
    assert output["status"] == "missing_registry_objects"
    assert output["missing_registry_objects"] == {"area": ["missing_area"]}


def test_retired_label_deletion_is_blocked_until_assignments_reach_zero() -> None:
    manifest = _manifest()
    live = _live_fixture()
    live["labels"].append({"label_id": "sleep", "name": "Sleep"})

    deletable, assigned = plan_retired_label_deletions(manifest, live)

    assert "sleep" not in deletable
    assert assigned["sleep"] == ["entity:automation.alarm_wake_up"]

    alarm = next(
        item
        for item in live["entities"]
        if item["entity_id"] == "automation.alarm_wake_up"
    )
    alarm["labels"] = ["unmanaged_personal"]
    deletable, assigned = plan_retired_label_deletions(manifest, live)

    assert "sleep" in deletable
    assert "sleep" not in assigned
