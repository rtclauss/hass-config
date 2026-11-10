from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ha_name_reconciliation import (  # noqa: E402
    audit_live,
    build_inventory,
    load_live_export,
    main,
    normalize_live_export,
)


def _live_export() -> dict[str, object]:
    return normalize_live_export(
        {
            "home_assistant_version": "2026.11.0",
            "floors": [
                {"floor_id": "main", "name": "Main Floor", "aliases": ["ground floor"]}
            ],
            "areas": [
                {"area_id": "dining_room", "name": "Dining room", "floor_id": "main"},
                {"area_id": "bedroom", "name": "Master Bedroom", "floor_id": "main"},
                {"area_id": "workshop", "name": "Workshop", "floor_id": "main"},
            ],
            "devices": [
                {
                    "id": "device-1",
                    "name": "Smart plug 3",
                    "name_by_user": "Coffee machine",
                    "area_id": "dining_room",
                    "via_device_id": "parent-1",
                    "labels": ["appliance"],
                }
            ],
            "entities": [
                {
                    "entity_id": "switch.coffee_machine",
                    "platform": "mqtt",
                    "device_id": "device-1",
                    "name": "Coffee machine",
                    "original_name": "Switch",
                    "aliases": ["Coffee switch"],
                    "labels": ["voice_controlled"],
                    "config_entry_id": "entry-1",
                    "unique_id": "private-runtime-id",
                },
                {
                    "entity_id": "sensor.coffee_machine_power",
                    "platform": "mqtt",
                    "device_id": "device-1",
                    "name": "Coffee machine Power usage",
                    "original_name": "Power",
                    "disabled_by": "integration",
                    "hidden_by": "user",
                },
                {
                    "entity_id": "sensor.coffee_machine_energy",
                    "platform": "mqtt",
                    "device_id": "device-1",
                    "name": "Daily usage",
                    "original_name": "Energy",
                    "area_id": "workshop",
                },
                {
                    "entity_id": "input_boolean.standalone",
                    "platform": "input_boolean",
                    "name": "Standalone",
                },
            ],
        }
    )


def test_normalize_live_export_accepts_wrapped_registry_results() -> None:
    live = normalize_live_export(
        {
            "entities": {"entities": [{"entity_id": "sensor.b"}, {"entity_id": "sensor.a"}]},
            "devices": {"result": [{"id": "device-1"}]},
            "areas": {"areas": []},
            "floors": {"result": []},
        }
    )

    assert [entity["entity_id"] for entity in live["entities"]] == ["sensor.a", "sensor.b"]
    assert live["devices"] == [{"id": "device-1"}]


def test_normalize_live_export_rejects_non_list_registry_data() -> None:
    with pytest.raises(ValueError, match="entities must be a list"):
        normalize_live_export({"entities": {"unexpected": "shape"}})


def test_inventory_resolves_entity_device_area_and_floor_context() -> None:
    rows = {row["entity_id"]: row for row in build_inventory(_live_export())}

    inherited = rows["switch.coffee_machine"]
    assert inherited["device_name"] == "Coffee machine"
    assert inherited["device_original_name"] == "Smart plug 3"
    assert inherited["entity_aliases"] == '["Coffee switch"]'
    assert inherited["entity_labels"] == '["voice_controlled"]'
    assert inherited["device_labels"] == '["appliance"]'
    assert inherited["config_entry_id"] == "entry-1"
    assert inherited["unique_id"] == "private-runtime-id"
    assert inherited["parent_device_id"] == "parent-1"
    assert inherited["area_id"] == "dining_room"
    assert inherited["area_inherited_from_device"] is True
    assert inherited["floor_name"] == "Main Floor"
    assert inherited["floor_aliases"] == '["ground floor"]'

    overridden = rows["sensor.coffee_machine_energy"]
    assert overridden["area_id"] == "workshop"
    assert overridden["area_inherited_from_device"] is False


def test_audit_reports_2026_11_review_groups_without_automatic_renames() -> None:
    audit = audit_live(_live_export())

    assert audit["findings"]["area_case_drift"] == [
        {
            "area_id": "dining_room",
            "current_name": "Dining room",
            "expected_name": "Dining Room",
        }
    ]
    assert audit["findings"]["area_name_drift"] == [
        {
            "area_id": "bedroom",
            "current_name": "Master Bedroom",
            "expected_name": "Owner Suite Bedroom",
            "room_key": "owner_suite_bedroom",
        }
    ]
    assert audit["findings"]["areas_without_room_registry_match"] == [
        {"area_id": "workshop", "current_name": "Workshop"}
    ]
    reasons = {
        item["entity_id"]: item["reason"]
        for item in audit["findings"]["entity_name_reviews"]
    }
    assert reasons == {
        "sensor.coffee_machine_energy": "custom_entity_name_needs_context_review",
        "sensor.coffee_machine_power": "entity_override_repeats_device_name",
        "switch.coffee_machine": "possible_main_entity_candidate",
    }


def test_audit_summary_covers_disabled_hidden_child_and_contextless_objects() -> None:
    summary = audit_live(_live_export())["summary"]

    assert summary["home_assistant_version"] == "2026.11.0"
    assert summary["floor_count"] == 1
    assert summary["area_count"] == 3
    assert summary["device_count"] == 1
    assert summary["child_device_count"] == 1
    assert summary["entity_count"] == 4
    assert summary["disabled_entity_count"] == 1
    assert summary["hidden_entity_count"] == 1
    assert summary["entity_without_device_count"] == 1
    assert summary["entity_without_area_count"] == 1
    assert summary["entity_name_override_count"] == 4
    assert summary["device_name_override_count"] == 1


def test_name_reconciliation_docs_are_linked_from_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "ha_name_reconciliation.md").read_text(encoding="utf-8")

    assert "[Home Assistant Name Reconciliation](docs/ha_name_reconciliation.md)" in readme
    assert "never commit" in docs
    assert "does not write" in docs


def test_name_reconciliation_script_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/ha_name_reconciliation.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Home Assistant 2026.11 naming metadata" in result.stdout


def test_cli_reads_private_export_and_emits_summary_csv_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export_path = tmp_path / "live.json"
    export_path.write_text(json.dumps(_live_export()), encoding="utf-8")

    assert main(["audit-live", "--live-json", str(export_path), "--summary-only"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["entity_count"] == 4
    assert "findings" not in summary

    assert main(["inventory", "--live-json", str(export_path), "--format", "csv"]) == 0
    csv_output = capsys.readouterr().out
    assert csv_output.startswith("entity_id,platform,config_entry_id,unique_id,original_name")
    assert "switch.coffee_machine" in csv_output

    assert main(["export-live", "--live-json", str(export_path)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["home_assistant_version"] == "2026.11.0"


def test_load_live_export_accepts_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_live_export())))

    live = load_live_export(Path("-"))

    assert len(live["entities"]) == 4


def test_audit_reports_dangling_area_references() -> None:
    live = _live_export()
    live["devices"].append({"id": "device-gone", "name": "Old plug", "area_id": "deleted-area"})
    live["entities"].append(
        {"entity_id": "light.orphaned", "platform": "mqtt", "area_id": "deleted-area"}
    )

    audit = audit_live(live)

    assert audit["findings"]["dangling_area_references"] == [
        {"kind": "device", "id": "device-gone", "area_id": "deleted-area"},
        {"kind": "entity", "id": "light.orphaned", "area_id": "deleted-area"},
    ]
    assert audit["summary"]["dangling_area_reference_count"] == 2
