from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSIGNMENTS_PATH = ROOT / "docs" / "ha_label_assignments.json"
HELPER_DOMAINS = {
    "counter",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "schedule",
    "timer",
}
BEHAVIOR_DOMAINS = {"automation", "scene", "script"}
ENTITY_REFERENCE_DOMAINS = {
    "air_quality",
    "alarm_control_panel",
    "alert",
    "assist_satellite",
    "automation",
    "binary_sensor",
    "button",
    "calendar",
    "camera",
    "climate",
    "conversation",
    "counter",
    "cover",
    "date",
    "datetime",
    "device_tracker",
    "event",
    "fan",
    "group",
    "humidifier",
    "image",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "lawn_mower",
    "light",
    "lock",
    "media_player",
    "number",
    "person",
    "plant",
    "remote",
    "scene",
    "schedule",
    "script",
    "select",
    "sensor",
    "siren",
    "sun",
    "switch",
    "text",
    "time",
    "timer",
    "todo",
    "update",
    "vacuum",
    "valve",
    "water_heater",
    "weather",
    "zone",
}
ENTITY_ID_PATTERN = re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z0-9_]+\b")
# A service call is shaped exactly like an entity_id, so `action: light.turn_on`
# was collected as an entity and put `light.turn_on` in the reference graph — the
# same pseudo-node problem as the Jinja attributes filtered above.
SERVICE_CALL_PATTERN = re.compile(
    r"(?:^|[\s,{])(?:-\s*)?(?:action|service):\s*[\"']?([a-z_][a-z0-9_]*\.[a-z0-9_]+)"
)
# On the behavior domains the same token can be either. `action: script.turn_on`
# is the service; `action: script.adaptive_light_turn_on` is a script entity
# being invoked, which is a real edge worth keeping. Only these reserved verbs
# are services — no script/scene/automation in this repo is named after one.
BEHAVIOR_SERVICE_VERBS = {
    "apply",
    "create",
    "reload",
    "toggle",
    "trigger",
    "turn_off",
    "turn_on",
}
# These read as services wherever they appear, including prose — a `description:`
# explaining "invoked non-blocking via script.turn_on" is not a reference. Kept
# narrow on purpose: no entity in the live registry (7024 of them) uses one of
# these as its object_id, whereas a verb like `trigger` or `create` plausibly
# could, so those stay confined to the `action:` position above.
UNAMBIGUOUS_SERVICE_VERBS = {"reload", "toggle", "turn_off", "turn_on"}
TOP_LEVEL_PATTERN = re.compile(r"^([a-z_][a-z0-9_ ]*):(?:\s|$)")
DICT_ITEM_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):(?:\s|$)")
LIST_ITEM_PATTERN = re.compile(r"^  -\s+")


def slugify(value: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", normalized)).strip("_")


def load_assignment_manifest(path: Path = DEFAULT_ASSIGNMENTS_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Assignment manifest root must be an object")
    return data


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def _section_blocks(path: Path, section_name: str) -> list[list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    section_lines: list[str] = []
    in_section = False
    for line in lines:
        top = TOP_LEVEL_PATTERN.match(line)
        if top:
            in_section = top.group(1).strip() == section_name
            continue
        if in_section:
            section_lines.append(line)

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in section_lines:
        starts_item = (
            LIST_ITEM_PATTERN.match(line)
            if section_name in {"automation", "scene"}
            else DICT_ITEM_PATTERN.match(line)
        )
        if starts_item:
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _field_from_block(block: list[str], field: str) -> str | None:
    pattern = re.compile(rf"^\s{{2,4}}(?:-\s+)?{re.escape(field)}:\s*(.*)$")
    for line in block:
        if match := pattern.match(line):
            return _strip_scalar(match.group(1))
    return None


def _is_service_call(token: str) -> bool:
    """True for `light.turn_on`-style service names, false for entity ids.

    Only meaningful for a token that appeared as the value of `action:`/`service:`.
    """
    domain, _, object_id = token.partition(".")
    if domain in BEHAVIOR_DOMAINS:
        # `action: script.foo` invokes the script entity; `action: script.turn_on`
        # calls the service.
        return object_id in BEHAVIOR_SERVICE_VERBS
    return True


def _strip_service_calls(content: str) -> str:
    """Blank out service names so they are not mistaken for entity references.

    Only the service token itself is removed, so an entity_id sharing the line
    (`{action: light.turn_on, entity_id: light.office}`) still gets collected.
    """
    spans = [
        match.span(1)
        for match in SERVICE_CALL_PATTERN.finditer(content)
        if _is_service_call(match.group(1))
    ]
    if not spans:
        return content
    parts: list[str] = []
    previous = 0
    for start, end in spans:
        parts.append(content[previous:start])
        parts.append(" ")
        previous = end
    parts.append(content[previous:])
    return "".join(parts)


def _references_from_block(block: list[str]) -> list[str]:
    references: set[str] = set()
    for line in block:
        content = _strip_service_calls(line.split("#", 1)[0])
        references.update(
            reference
            for reference in ENTITY_ID_PATTERN.findall(content)
            if reference.split(".", 1)[0] in ENTITY_REFERENCE_DOMAINS
            and reference.split(".", 1)[1] not in UNAMBIGUOUS_SERVICE_VERBS
        )
    return sorted(references)


def discover_repository_inventory(root: Path = ROOT) -> dict[str, list[dict[str, Any]]]:
    behaviors: list[dict[str, Any]] = []
    helpers: list[dict[str, Any]] = []
    for path in sorted((root / "packages").glob("*.yaml")):
        relative_path = str(path.relative_to(root))
        for block in _section_blocks(path, "automation"):
            unique_id = _field_from_block(block, "id")
            alias = _field_from_block(block, "alias") or unique_id or ""
            entity_id = f"automation.{slugify(alias)}"
            row: dict[str, Any] = {
                "kind": "automation",
                "entity_id": entity_id,
                "package": relative_path,
                "references": _references_from_block(block),
            }
            if unique_id:
                row["unique_id"] = unique_id
            behaviors.append(row)

        for block in _section_blocks(path, "script"):
            match = DICT_ITEM_PATTERN.match(block[0])
            if not match:
                continue
            object_id = match.group(1)
            behaviors.append(
                {
                    "kind": "script",
                    "entity_id": f"script.{object_id}",
                    "package": relative_path,
                    "references": _references_from_block(block),
                }
            )

        for block in _section_blocks(path, "scene"):
            unique_id = _field_from_block(block, "id")
            name = _field_from_block(block, "name") or ""
            row = {
                "kind": "scene",
                "entity_id": f"scene.{slugify(name)}",
                "package": relative_path,
                "references": _references_from_block(block),
            }
            if unique_id:
                row["unique_id"] = unique_id
            behaviors.append(row)

        text = path.read_text(encoding="utf-8")
        top_sections = {
            match.group(1).strip()
            for line in text.splitlines()
            if (match := TOP_LEVEL_PATTERN.match(line))
        }
        for domain in sorted(HELPER_DOMAINS & top_sections):
            for block in _section_blocks(path, domain):
                match = DICT_ITEM_PATTERN.match(block[0])
                if not match:
                    continue
                helpers.append(
                    {
                        "entity_id": f"{domain}.{match.group(1)}",
                        "package": relative_path,
                        "references": _references_from_block(block),
                    }
                )

    return {
        "behaviors": sorted(behaviors, key=lambda item: (item["kind"], item["entity_id"])),
        "helpers": sorted(helpers, key=lambda item: item["entity_id"]),
    }


def build_reference_graph(root: Path = ROOT) -> dict[str, Any]:
    inventory = discover_repository_inventory(root)
    graph = {
        item["entity_id"]: item["references"]
        for item in inventory["behaviors"]
    }
    referenced_by: dict[str, list[str]] = defaultdict(list)
    for source, targets in graph.items():
        for target in targets:
            referenced_by[target].append(source)
    return {
        "graph": graph,
        "referenced_by": {
            target: sorted(sources) for target, sources in sorted(referenced_by.items())
        },
        "node_count": len(graph),
        "edge_count": sum(len(targets) for targets in graph.values()),
    }


def _behavior_key(item: dict[str, Any]) -> tuple[str, str]:
    kind = str(item.get("kind", ""))
    if item.get("unique_id"):
        return kind, f"unique_id:{item['unique_id']}"
    return kind, f"entity_id:{item.get('entity_id', '')}"


def validate_assignment_manifest(
    manifest: dict[str, Any],
    *,
    active_label_ids: set[str] | None = None,
    root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    managed = manifest.get("managed_labels")
    retired = manifest.get("retired_labels")
    if not isinstance(managed, list) or not managed:
        errors.append("managed_labels must be a non-empty list")
        managed = []
    if not isinstance(retired, list):
        errors.append("retired_labels must be a list")
        retired = []

    managed_set = {str(label) for label in managed}
    retired_set = {str(label) for label in retired}
    if len(managed_set) != len(managed):
        errors.append("managed_labels must be unique")
    if managed_set & retired_set:
        errors.append("managed_labels and retired_labels must not overlap")
    if active_label_ids is not None and managed_set != active_label_ids:
        errors.append(
            "managed_labels must exactly match active taxonomy labels: "
            f"missing={sorted(active_label_ids - managed_set)}, "
            f"extra={sorted(managed_set - active_label_ids)}"
        )

    for section in ("behaviors", "helpers"):
        rows = manifest.get(section)
        if not isinstance(rows, list):
            errors.append(f"{section} must be a list")
            continue
        seen: set[tuple[str, str] | str] = set()
        for index, row in enumerate(rows):
            prefix = f"{section}[{index}]"
            if not isinstance(row, dict):
                errors.append(f"{prefix} must be an object")
                continue
            entity_id = str(row.get("entity_id", ""))
            if "." not in entity_id:
                errors.append(f"{prefix} has invalid entity_id")
            labels = row.get("labels")
            if not isinstance(labels, list) or not labels:
                errors.append(f"{prefix} must have at least one label")
                continue
            unknown = sorted(set(labels) - managed_set)
            if unknown:
                errors.append(f"{prefix} uses unmanaged labels: {', '.join(unknown)}")
            key: tuple[str, str] | str
            if section == "behaviors":
                kind = str(row.get("kind", ""))
                if kind not in BEHAVIOR_DOMAINS:
                    errors.append(f"{prefix} has invalid kind: {kind}")
                if str(row.get("source", "")) not in {"repository", "live_only"}:
                    errors.append(f"{prefix} has invalid source")
                key = _behavior_key(row)
            else:
                if str(row.get("source", "")) not in {"repository", "live_registry"}:
                    errors.append(f"{prefix} has invalid source")
                key = entity_id
            if key in seen:
                errors.append(f"{prefix} duplicates {key}")
            seen.add(key)

    for area_id, labels in manifest.get("area_assignments", {}).items():
        if not area_id or not isinstance(labels, list) or not labels:
            errors.append(f"area assignment {area_id!r} must have labels")
            continue
        unknown = sorted(set(labels) - managed_set)
        if unknown:
            errors.append(f"area {area_id} uses unmanaged labels: {', '.join(unknown)}")

    for index, rule in enumerate(manifest.get("rules", [])):
        prefix = f"rules[{index}]"
        if not rule.get("id"):
            errors.append(f"{prefix} requires id")
        if not rule.get("object_types"):
            errors.append(f"{prefix} requires object_types")
        unknown = sorted(set(rule.get("labels", [])) - managed_set)
        if unknown:
            errors.append(f"{prefix} uses unmanaged labels: {', '.join(unknown)}")

    inventory = discover_repository_inventory(root)
    manifest_repo_behaviors = {
        _behavior_key(item)
        for item in manifest.get("behaviors", [])
        if item.get("source") == "repository"
    }
    discovered_behaviors = {_behavior_key(item) for item in inventory["behaviors"]}
    missing_behaviors = sorted(discovered_behaviors - manifest_repo_behaviors)
    extra_behaviors = sorted(manifest_repo_behaviors - discovered_behaviors)
    if missing_behaviors:
        errors.append(f"repository behaviors missing from manifest: {missing_behaviors}")
    if extra_behaviors:
        errors.append(f"manifest repository behaviors not found in packages: {extra_behaviors}")

    manifest_repo_helpers = {
        str(item.get("entity_id"))
        for item in manifest.get("helpers", [])
        if item.get("source") == "repository"
    }
    discovered_helpers = {item["entity_id"] for item in inventory["helpers"]}
    if missing_helpers := sorted(discovered_helpers - manifest_repo_helpers):
        errors.append(f"repository helpers missing from manifest: {missing_helpers}")
    if extra_helpers := sorted(manifest_repo_helpers - discovered_helpers):
        errors.append(f"manifest repository helpers not found in packages: {extra_helpers}")

    scene_ids = [
        str(item.get("unique_id", ""))
        for item in inventory["behaviors"]
        if item["kind"] == "scene"
    ]
    if not scene_ids or any(not scene_id for scene_id in scene_ids):
        errors.append("all repository scenes must have stable ids")
    if len(scene_ids) != len(set(scene_ids)):
        errors.append("repository scene ids must be unique")
    return errors


def _matches_values(actual: str | None, expected: Iterable[str]) -> bool:
    if actual is None:
        return False
    folded = actual.casefold()
    return any(folded == str(value).casefold() for value in expected)


def _matches_patterns(actual: str | None, patterns: Iterable[str]) -> bool:
    if actual is None:
        return False
    return any(re.search(pattern, actual, re.IGNORECASE) for pattern in patterns)


def rule_matches(rule: dict[str, Any], entry: dict[str, Any], object_type: str) -> bool:
    if object_type not in rule.get("object_types", []):
        return False
    match = rule.get("match", {})
    checks: list[bool] = []
    if "domains" in match:
        domain = str(entry.get("entity_id", "")).split(".", 1)[0]
        checks.append(_matches_values(domain, match["domains"]))
    if "platforms" in match:
        checks.append(_matches_values(entry.get("platform"), match["platforms"]))
    if "entity_id_patterns" in match:
        checks.append(
            _matches_patterns(str(entry.get("entity_id", "")), match["entity_id_patterns"])
        )
    if "manufacturers" in match:
        checks.append(_matches_values(entry.get("manufacturer"), match["manufacturers"]))
    if "manufacturer_patterns" in match:
        checks.append(
            _matches_patterns(entry.get("manufacturer"), match["manufacturer_patterns"])
        )
    if "area_ids" in match:
        checks.append(_matches_values(entry.get("area_id"), match["area_ids"]))
    if "device_name_patterns" in match:
        device_text = " ".join(
            str(entry.get(field) or "")
            for field in ("name", "name_by_user", "model")
        )
        checks.append(_matches_patterns(device_text, match["device_name_patterns"]))
    if not checks:
        return False
    return any(checks) if rule.get("match_mode") == "any" else all(checks)


def _live_entity_id_by_unique_id(live: dict[str, Any]) -> dict[tuple[str, str], str]:
    """Map each live entity's (domain, unique_id) to its registry entity_id.

    Home Assistant derives an automation's entity_id from its alias at *first
    registration* and then pins it; later alias edits do not move it. The repo
    cannot know the original alias offline, so the only stable link between a
    repo behavior and its live entity is the `id:` field (its unique_id).

    unique_id uniqueness is enforced per-domain (per platform/config entry),
    not globally, so the same unique_id string can legitimately appear on
    both an automation and a scene. Keying by unique_id alone collapses
    those into one entry — normalized entities are sorted by entity_id, so
    the alphabetically-later domain's entity silently overwrites the
    earlier one (Codex P1 on #903/#906). Keying by (domain, unique_id)
    keeps them distinct.
    """
    result: dict[tuple[str, str], str] = {}
    for entity in live.get("entities", []):
        unique_id = entity.get("unique_id")
        entity_id = entity.get("entity_id")
        if unique_id and entity_id:
            domain = str(entity_id).split(".", 1)[0]
            result[(domain, str(unique_id))] = str(entity_id)
    return result


def _labels_by_entity(
    rows: Iterable[dict[str, Any]],
    unique_id_to_entity_id: dict[tuple[str, str], str] | None = None,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        entity_id = str(row["entity_id"])
        unique_id = row.get("unique_id")
        # Prefer the live entity_id keyed by (domain, unique_id): a renamed
        # automation's slug-derived entity_id no longer matches the pinned
        # registry id, and labeling the stale slug would silently miss the
        # real entity. The domain comes from the manifest row's own
        # entity_id, so a unique_id reused across domains (e.g. an
        # automation and a scene both named "tv_paused") resolves each row
        # against its own domain instead of colliding. Fall back to the slug
        # when the behavior is not in the registry yet (not deployed).
        if unique_id_to_entity_id and unique_id:
            domain = entity_id.split(".", 1)[0]
            entity_id = unique_id_to_entity_id.get((domain, str(unique_id)), entity_id)
        result[entity_id].update(str(label) for label in row["labels"])
    return result


def compile_assignments(
    manifest: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, dict[str, set[str]]]:
    desired: dict[str, dict[str, set[str]]] = {
        "area": defaultdict(set),
        "device": defaultdict(set),
        "entity": defaultdict(set),
    }
    for area_id, labels in manifest.get("area_assignments", {}).items():
        desired["area"][str(area_id)].update(labels)

    explicit_entities = _labels_by_entity(
        list(manifest.get("behaviors", [])) + list(manifest.get("helpers", [])),
        _live_entity_id_by_unique_id(live),
    )
    for entity_id, labels in explicit_entities.items():
        desired["entity"][entity_id].update(labels)

    for entity in live.get("entities", []):
        device_id = entity.get("device_id")
        for rule in manifest.get("rules", []):
            if not rule_matches(rule, entity, "entity"):
                continue
            labels = set(str(label) for label in rule.get("labels", []))
            desired["entity"][str(entity["entity_id"])].update(labels)
            if rule.get("apply_to_device") and device_id:
                desired["device"][str(device_id)].update(labels)

    for device in live.get("devices", []):
        device_id = str(device.get("id", ""))
        for rule in manifest.get("rules", []):
            if rule_matches(rule, device, "device"):
                desired["device"][device_id].update(
                    str(label) for label in rule.get("labels", [])
                )

    return desired


def _registry_rows(live: dict[str, Any], registry: str) -> list[dict[str, Any]]:
    return live.get({"area": "areas", "device": "devices", "entity": "entities"}[registry], [])


def _registry_id(row: dict[str, Any], registry: str) -> str:
    return str(row[{"area": "area_id", "device": "id", "entity": "entity_id"}[registry]])


def find_missing_registry_objects(
    desired: dict[str, dict[str, set[str]]],
    live: dict[str, Any],
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for registry in ("area", "device", "entity"):
        live_ids = {
            _registry_id(row, registry)
            for row in _registry_rows(live, registry)
        }
        registry_missing = sorted(set(desired[registry]) - live_ids)
        if registry_missing:
            missing[registry] = registry_missing
    return missing


def plan_assignment_operations(
    manifest: dict[str, Any],
    live: dict[str, Any],
) -> list[dict[str, Any]]:
    desired = compile_assignments(manifest, live)
    managed = set(manifest.get("managed_labels", [])) | set(
        manifest.get("retired_labels", [])
    )
    operations: list[dict[str, Any]] = []
    for registry in ("area", "device", "entity"):
        rows_by_id = {
            _registry_id(row, registry): row
            for row in _registry_rows(live, registry)
        }
        object_ids = set(rows_by_id) | set(desired[registry])
        for object_id in sorted(object_ids):
            row = rows_by_id.get(object_id)
            if row is None:
                continue
            before = set(str(label) for label in row.get("labels", []) or [])
            after = (before - managed) | desired[registry].get(object_id, set())
            if before == after:
                continue
            operations.append(
                {
                    "registry": registry,
                    "object_id": object_id,
                    "before": sorted(before),
                    "after": sorted(after),
                    "managed_add": sorted(after - before),
                    "managed_remove": sorted(before - after),
                }
            )
    return operations


def audit_assignments(
    manifest: dict[str, Any],
    live: dict[str, Any],
    *,
    active_label_scopes: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    desired = compile_assignments(manifest, live)
    live_ids = {
        registry: {
            _registry_id(row, registry)
            for row in _registry_rows(live, registry)
        }
        for registry in ("area", "device", "entity")
    }
    missing_registry_objects = find_missing_registry_objects(desired, live)
    # Resolve through the same (domain, unique_id) -> entity_id mapping
    # compile_assignments uses, so a renamed behavior's audit result agrees
    # with what was actually assigned instead of comparing against its
    # stale slug-derived manifest ID (Codex P2 on #903/#906).
    required_entities = _labels_by_entity(
        list(manifest.get("behaviors", [])) + list(manifest.get("helpers", [])),
        _live_entity_id_by_unique_id(live),
    )
    live_entities_by_id = {
        str(entity["entity_id"]): entity for entity in live.get("entities", [])
    }
    missing_entities = sorted(set(required_entities) - live_ids["entity"])
    coverage_by_domain: dict[str, dict[str, int]] = {}
    for domain in sorted(BEHAVIOR_DOMAINS | HELPER_DOMAINS):
        required = {
            entity_id
            for entity_id in required_entities
            if entity_id.split(".", 1)[0] == domain
        }
        present = required & live_ids["entity"]
        planned_labeled = {
            entity_id
            for entity_id in present
            if desired["entity"].get(entity_id)
        }
        fully_assigned_live = {
            entity_id
            for entity_id in present
            if required_entities[entity_id]
            <= set(live_entities_by_id[entity_id].get("labels", []) or [])
        }
        partially_assigned_live = {
            entity_id
            for entity_id in present
            if required_entities[entity_id]
            & set(live_entities_by_id[entity_id].get("labels", []) or [])
        }
        if required:
            coverage_by_domain[domain] = {
                "required": len(required),
                "present": len(present),
                "fully_assigned_live": len(fully_assigned_live),
                "partially_assigned_live": len(partially_assigned_live),
                "planned_labeled": len(planned_labeled),
                "missing": len(required - present),
            }

    retired = set(manifest.get("retired_labels", []))
    retired_assignments: dict[str, list[str]] = defaultdict(list)
    for registry in ("area", "device", "entity"):
        for row in _registry_rows(live, registry):
            object_id = _registry_id(row, registry)
            for label in set(row.get("labels", []) or []) & retired:
                retired_assignments[label].append(f"{registry}:{object_id}")

    label_counts = Counter()
    for registry in desired.values():
        for labels in registry.values():
            label_counts.update(labels)
    minimum = int(manifest.get("minimum_items_for_extension", 0))
    extension_counts = {
        label: label_counts[label]
        for label in manifest.get("extension_labels", [])
    }
    extension_threshold_failures = {
        label: count for label, count in extension_counts.items() if count < minimum
    }

    scope_errors: list[dict[str, str]] = []
    if active_label_scopes is not None:
        registry_scope = {"area": "area", "device": "device", "entity": "entity"}
        for registry, assignments in desired.items():
            for object_id, labels in assignments.items():
                for label in labels:
                    if registry_scope[registry] not in active_label_scopes.get(label, set()):
                        scope_errors.append(
                            {
                                "registry": registry,
                                "object_id": object_id,
                                "label_id": label,
                            }
                        )

    return {
        "coverage_by_domain": coverage_by_domain,
        "missing_entities": missing_entities,
        "missing_registry_objects": missing_registry_objects,
        "runtime_only_behaviors": sorted(
            item["entity_id"]
            for item in manifest.get("behaviors", [])
            if item.get("source") == "live_only"
        ),
        "retired_assignments": {
            label: sorted(items) for label, items in sorted(retired_assignments.items())
        },
        "extension_counts": extension_counts,
        "extension_threshold_failures": extension_threshold_failures,
        "scope_errors": scope_errors,
        "planned_operation_count": len(plan_assignment_operations(manifest, live)),
        "desired_assignment_counts": {
            registry: sum(len(labels) for labels in assignments.values())
            for registry, assignments in desired.items()
        },
    }


def apply_assignment_operations(
    operations: list[dict[str, Any]],
    command: Callable[..., object],
    progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for operation in operations:
        registry = operation["registry"]
        object_id = operation["object_id"]
        labels = operation["after"]
        if registry == "area":
            result = command(
                "config/area_registry/update", area_id=object_id, labels=labels
            )
        elif registry == "device":
            result = command(
                "config/device_registry/update", device_id=object_id, labels=labels
            )
        elif registry == "entity":
            result = command(
                "config/entity_registry/update", entity_id=object_id, labels=labels
            )
        else:
            raise ValueError(f"Unsupported registry: {registry}")
        results.append({"operation": operation, "result": result})
        if progress is not None:
            progress(len(results), len(operations))
    return results


def plan_retired_label_deletions(
    manifest: dict[str, Any],
    live: dict[str, Any],
) -> tuple[list[str], dict[str, list[str]]]:
    retired = set(manifest.get("retired_labels", []))
    assigned: dict[str, list[str]] = defaultdict(list)
    for registry in ("area", "device", "entity"):
        for row in _registry_rows(live, registry):
            object_id = _registry_id(row, registry)
            for label in set(row.get("labels", []) or []) & retired:
                assigned[label].append(f"{registry}:{object_id}")
    live_label_ids = {
        str(label.get("label_id"))
        for label in live.get("labels", [])
    }
    deletable = sorted((retired & live_label_ids) - set(assigned))
    return deletable, {label: sorted(items) for label, items in sorted(assigned.items())}
