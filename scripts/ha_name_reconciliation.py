from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ha_label_taxonomy import HomeAssistantWebSocket
from scripts.room_name_registry import ROOM_NAME_SPECS


def _collection(raw: object, key: str) -> list[dict[str, Any]]:
    value = raw
    if isinstance(value, dict):
        if key in value:
            value = value[key]
        elif "result" in value:
            value = value["result"]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return [item for item in value if isinstance(item, dict)]


def normalize_live_export(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "home_assistant_version": raw.get("home_assistant_version"),
        "entities": sorted(
            _collection(raw.get("entities", []), "entities"),
            key=lambda item: str(item.get("entity_id", "")),
        ),
        "devices": sorted(
            _collection(raw.get("devices", []), "devices"),
            key=lambda item: str(item.get("id", "")),
        ),
        "areas": sorted(
            _collection(raw.get("areas", []), "areas"),
            key=lambda item: str(item.get("area_id", "")),
        ),
        "floors": sorted(
            _collection(raw.get("floors", []), "floors"),
            key=lambda item: str(item.get("floor_id", "")),
        ),
    }


def load_live_export(path: Path) -> dict[str, Any]:
    if str(path) == "-":
        return normalize_live_export(json.load(sys.stdin))
    with path.open(encoding="utf-8") as file:
        return normalize_live_export(json.load(file))


def fetch_live_from_ha() -> dict[str, Any]:
    import os

    url = os.environ.get("HA_URL")
    token = os.environ.get("HA_TOKEN")
    if not url or not token:
        raise RuntimeError("Set HA_URL and HA_TOKEN, or pass --live-json")

    with HomeAssistantWebSocket(url=url, token=token) as client:
        config = client.command("get_config")
        raw = {
            "home_assistant_version": (
                config.get("version") if isinstance(config, dict) else None
            ),
            "entities": client.command("config/entity_registry/list"),
            "devices": client.command("config/device_registry/list"),
            "areas": client.command("config/area_registry/list"),
            "floors": client.command("config/floor_registry/list"),
        }
    return normalize_live_export(raw)


def _display_device_name(device: dict[str, Any] | None) -> str | None:
    if device is None:
        return None
    return device.get("name_by_user") or device.get("name")


def _json_list(value: object) -> str:
    return json.dumps(value if isinstance(value, list) else [], separators=(",", ":"))


def build_inventory(live: dict[str, Any]) -> list[dict[str, Any]]:
    devices = {str(item.get("id")): item for item in live["devices"] if item.get("id")}
    areas = {
        str(item.get("area_id")): item for item in live["areas"] if item.get("area_id")
    }
    floors = {
        str(item.get("floor_id")): item
        for item in live["floors"]
        if item.get("floor_id")
    }
    rows: list[dict[str, Any]] = []

    for entity in live["entities"]:
        device = devices.get(str(entity.get("device_id")))
        entity_area_id = entity.get("area_id")
        device_area_id = device.get("area_id") if device else None
        area_id = entity_area_id or device_area_id
        area = areas.get(str(area_id))
        floor = floors.get(str(area.get("floor_id"))) if area else None
        rows.append(
            {
                "entity_id": entity.get("entity_id"),
                "platform": entity.get("platform"),
                "config_entry_id": entity.get("config_entry_id"),
                "unique_id": entity.get("unique_id"),
                "original_name": entity.get("original_name"),
                "entity_name_override": entity.get("name"),
                "entity_aliases": _json_list(entity.get("aliases")),
                "entity_labels": _json_list(entity.get("labels")),
                "entity_category": entity.get("entity_category"),
                "disabled_by": entity.get("disabled_by"),
                "hidden_by": entity.get("hidden_by"),
                "device_id": entity.get("device_id"),
                "device_name": _display_device_name(device),
                "device_original_name": device.get("name") if device else None,
                "device_name_override": device.get("name_by_user") if device else None,
                "device_labels": _json_list(device.get("labels") if device else None),
                "parent_device_id": device.get("via_device_id") if device else None,
                "area_id": area_id,
                "area_name": area.get("name") if area else None,
                "area_aliases": _json_list(area.get("aliases") if area else None),
                "area_labels": _json_list(area.get("labels") if area else None),
                "area_inherited_from_device": bool(not entity_area_id and device_area_id),
                "floor_id": area.get("floor_id") if area else None,
                "floor_name": floor.get("name") if floor else None,
                "floor_aliases": _json_list(floor.get("aliases") if floor else None),
            }
        )
    return rows


def _canonical_area_names() -> dict[str, tuple[str, str]]:
    names: dict[str, tuple[str, str]] = {}
    for spec in ROOM_NAME_SPECS:
        for label in {
            spec.home_assistant_area,
            spec.preferred_label,
            *spec.legacy_labels,
        }:
            names[label.casefold()] = (spec.key, spec.home_assistant_area)
    return names


def _area_findings(
    live: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    canonical = _canonical_area_names()
    case_drift: list[dict[str, str]] = []
    canonical_name_drift: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    for area in live["areas"]:
        area_id = str(area.get("area_id", ""))
        name = str(area.get("name", ""))
        match = canonical.get(name.casefold())
        if match is None:
            unmatched.append({"area_id": area_id, "current_name": name})
            continue
        room_key, expected = match
        if name.casefold() == expected.casefold() and name != expected:
            case_drift.append(
                {"area_id": area_id, "current_name": name, "expected_name": expected}
            )
        elif name != expected:
            canonical_name_drift.append(
                {
                    "area_id": area_id,
                    "current_name": name,
                    "expected_name": expected,
                    "room_key": room_key,
                }
            )
    return case_drift, canonical_name_drift, unmatched


def _entity_name_reviews(inventory: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    reviews: list[dict[str, str]] = []
    for row in inventory:
        entity_name = row.get("entity_name_override")
        device_name = row.get("device_name")
        if not entity_name or not device_name:
            continue
        entity_folded = str(entity_name).casefold()
        device_folded = str(device_name).casefold()
        if entity_folded == device_folded:
            reason = "possible_main_entity_candidate"
        elif entity_folded.startswith(f"{device_folded} "):
            reason = "entity_override_repeats_device_name"
        else:
            reason = "custom_entity_name_needs_context_review"
        reviews.append(
            {
                "entity_id": str(row["entity_id"]),
                "entity_name_override": str(entity_name),
                "device_name": str(device_name),
                "reason": reason,
            }
        )
    return reviews


def audit_live(live: dict[str, Any]) -> dict[str, Any]:
    inventory = build_inventory(live)
    area_case_drift, area_name_drift, unmatched_areas = _area_findings(live)
    entity_name_reviews = _entity_name_reviews(inventory)
    review_reason_counts: dict[str, int] = {}
    for review in entity_name_reviews:
        reason = review["reason"]
        review_reason_counts[reason] = review_reason_counts.get(reason, 0) + 1

    summary = {
        "home_assistant_version": live.get("home_assistant_version"),
        "floor_count": len(live["floors"]),
        "area_count": len(live["areas"]),
        "device_count": len(live["devices"]),
        "child_device_count": sum(bool(device.get("via_device_id")) for device in live["devices"]),
        "entity_count": len(inventory),
        "disabled_entity_count": sum(bool(row["disabled_by"]) for row in inventory),
        "hidden_entity_count": sum(bool(row["hidden_by"]) for row in inventory),
        "entity_without_device_count": sum(not row["device_id"] for row in inventory),
        "entity_without_area_count": sum(not row["area_id"] for row in inventory),
        "entity_name_override_count": sum(
            bool(row["entity_name_override"]) for row in inventory
        ),
        "device_name_override_count": sum(
            bool(device.get("name_by_user")) for device in live["devices"]
        ),
        "area_case_drift_count": len(area_case_drift),
        "area_name_drift_count": len(area_name_drift),
        "unmatched_area_count": len(unmatched_areas),
        "entity_name_review_count": len(entity_name_reviews),
        "entity_name_review_reason_counts": review_reason_counts,
    }
    return {
        "summary": summary,
        "findings": {
            "area_case_drift": area_case_drift,
            "area_name_drift": area_name_drift,
            "areas_without_room_registry_match": unmatched_areas,
            "entity_name_reviews": entity_name_reviews,
        },
    }


def _live_for_args(args: argparse.Namespace) -> dict[str, Any]:
    return load_live_export(args.live_json) if args.live_json else fetch_live_from_ha()


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _write_csv(rows: list[dict[str, Any]], output: TextIO) -> None:
    if not rows:
        return
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)


def command_export_live(args: argparse.Namespace) -> int:
    _print_json(_live_for_args(args))
    return 0


def command_audit_live(args: argparse.Namespace) -> int:
    audit = audit_live(_live_for_args(args))
    _print_json(audit["summary"] if args.summary_only else audit)
    return 0


def command_inventory(args: argparse.Namespace) -> int:
    rows = build_inventory(_live_for_args(args))
    if args.format == "csv":
        _write_csv(rows, sys.stdout)
    else:
        _print_json(rows)
    return 0


def _add_live_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--live-json",
        type=Path,
        help="Private export to inspect instead of connecting with HA_URL and HA_TOKEN.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export and audit Home Assistant 2026.11 naming metadata read-only."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-live")
    _add_live_source(export_parser)
    export_parser.set_defaults(handler=command_export_live)

    audit_parser = subparsers.add_parser("audit-live")
    _add_live_source(audit_parser)
    audit_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit entity and room names from output for safe sharing.",
    )
    audit_parser.set_defaults(handler=command_audit_live)

    inventory_parser = subparsers.add_parser("inventory")
    _add_live_source(inventory_parser)
    inventory_parser.add_argument("--format", choices=("csv", "json"), default="csv")
    inventory_parser.set_defaults(handler=command_inventory)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
