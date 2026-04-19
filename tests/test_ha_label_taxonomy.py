from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ha_label_taxonomy import (  # noqa: E402
    ALLOWED_LIFECYCLES,
    ALLOWED_SCOPES,
    LABEL_ID_PATTERN,
    audit_live,
    load_label_specs,
    plan_label_operations,
    validate_specs,
)

TAXONOMY_PATH = ROOT / "docs" / "ha_label_taxonomy.yaml"
DOC_PATH = ROOT / "docs" / "ha_labels.md"
README_PATH = ROOT / "README.md"


def test_ha_label_taxonomy_is_valid() -> None:
    specs = load_label_specs(TAXONOMY_PATH)

    assert validate_specs(specs) == []


def test_ha_label_ids_are_unique_stable_snake_case() -> None:
    specs = load_label_specs(TAXONOMY_PATH)
    label_ids = [spec.label_id for spec in specs]

    assert len(label_ids) == len(set(label_ids))
    assert all(LABEL_ID_PATTERN.match(label_id) for label_id in label_ids)


def test_ha_labels_have_required_description_scope_and_lifecycle() -> None:
    specs = load_label_specs(TAXONOMY_PATH)

    for spec in specs:
        assert spec.description
        assert spec.scopes
        assert set(spec.scopes) <= ALLOWED_SCOPES
        assert spec.lifecycle in ALLOWED_LIFECYCLES
        assert spec.owner
        assert spec.reason


def test_deprecated_ha_labels_require_replacement_or_removal_reason() -> None:
    specs = load_label_specs(TAXONOMY_PATH)

    for spec in specs:
        if spec.lifecycle == "deprecated":
            assert spec.replacement or spec.removal_reason


def test_hallway_label_remains_area_scoped_for_live_hallway_areas() -> None:
    specs = {spec.label_id: spec for spec in load_label_specs(TAXONOMY_PATH)}

    hallway = specs["hallway"]
    assert "area" in hallway.scopes
    assert "hallway" in hallway.reason
    assert "upstairs_hallway" in hallway.reason


def test_ha_label_docs_explain_source_of_truth_and_no_inheritance() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "docs/ha_label_taxonomy.yaml" in text
    assert "Do not rely on label inheritance" in text
    assert "does not automatically become an entity label" in text


def test_readme_links_to_ha_label_model() -> None:
    text = README_PATH.read_text(encoding="utf-8")

    assert "- [Home Assistant Label Model](docs/ha_labels.md)" in text


def test_live_audit_detects_missing_unknown_and_scope_mismatches() -> None:
    specs = load_label_specs(TAXONOMY_PATH)
    live = {
        "labels": [
            {
                "label_id": "hallway",
                "name": "Hallway",
                "description": "Shared hallway context that spans the main hallway and upstairs hallway areas.",
                "icon": "mdi:floor-plan",
                "color": "blue",
            },
            {"label_id": "ad_hoc", "name": "Ad Hoc"},
        ],
        "areas": [
            {"area_id": "hallway", "labels": ["hallway"]},
            {"area_id": "kitchen", "labels": ["media_scope"]},
            {"area_id": "garage", "labels": ["ad_hoc"]},
        ],
    }

    audit = audit_live(specs, live)

    assert "guest_sensitive" in audit["missing_labels"]
    assert audit["unknown_live_labels"] == ["ad_hoc"]
    assert {
        "area_id": "kitchen",
        "label_id": "media_scope",
        "reason": "label taxonomy does not allow area scope",
    } in audit["area_scope_mismatches"]
    assert {
        "area_id": "garage",
        "label_id": "ad_hoc",
        "reason": "label is not in taxonomy",
    } in audit["area_scope_mismatches"]


def test_apply_label_plan_never_removes_unknown_live_labels() -> None:
    specs = load_label_specs(TAXONOMY_PATH)
    live = {
        "labels": [
            {
                "label_id": "hallway",
                "name": "Old Hallway",
                "description": None,
                "icon": None,
                "color": None,
            },
            {"label_id": "ad_hoc", "name": "Ad Hoc"},
        ],
        "areas": [],
    }

    operations = plan_label_operations(specs, live)

    assert operations[0]["action"] == "update"
    assert operations[0]["label_id"] == "hallway"
    assert all(operation["action"] in {"create", "update"} for operation in operations)
    assert all(operation["label_id"] != "ad_hoc" for operation in operations)
