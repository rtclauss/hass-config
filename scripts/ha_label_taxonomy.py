from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import ssl
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY_PATH = ROOT / "docs" / "ha_label_taxonomy.yaml"

ALLOWED_SCOPES = {
    "area",
    "automation",
    "device",
    "entity",
    "helper",
    "scene",
    "script",
}
ALLOWED_LIFECYCLES = {"active", "deprecated", "reserved"}
LABEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class LabelSpec:
    label_id: str
    name: str
    description: str
    scopes: tuple[str, ...]
    lifecycle: str
    owner: str
    reason: str
    icon: str | None = None
    color: str | None = None
    replacement: str | None = None
    removal_reason: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LabelSpec":
        return cls(
            label_id=str(raw.get("label_id", "")),
            name=str(raw.get("name", "")),
            description=str(raw.get("description", "")),
            scopes=tuple(str(scope) for scope in raw.get("scopes", ())),
            lifecycle=str(raw.get("lifecycle", "")),
            owner=str(raw.get("owner", "")),
            reason=str(raw.get("reason", "")),
            icon=_optional_str(raw.get("icon")),
            color=_optional_str(raw.get("color")),
            replacement=_optional_str(raw.get("replacement")),
            removal_reason=_optional_str(raw.get("removal_reason")),
        )

    def live_fields(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
        }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if value == "":
        return ""
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _split_key_value(text: str, line_number: int) -> tuple[str, object]:
    if ":" not in text:
        raise ValueError(f"Line {line_number}: expected key: value")
    key, value = text.split(":", 1)
    return key.strip(), _parse_scalar(value)


def _parse_taxonomy_yaml(path: Path) -> dict[str, Any]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    document: dict[str, Any] = {}
    labels: list[dict[str, Any]] = []
    current_label: dict[str, Any] | None = None
    current_list_key: str | None = None
    in_labels = False

    for line_number, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        text = raw_line.strip()

        if indent == 0:
            key, value = _split_key_value(text, line_number)
            current_label = None
            current_list_key = None
            in_labels = key == "labels"
            if in_labels:
                document[key] = labels
            else:
                document[key] = value
            continue

        if not in_labels:
            raise ValueError(f"Line {line_number}: nested content is only supported under labels")

        if indent == 2 and text.startswith("- "):
            current_label = {}
            labels.append(current_label)
            current_list_key = None
            rest = text[2:].strip()
            if rest:
                key, value = _split_key_value(rest, line_number)
                current_label[key] = value
            continue

        if current_label is None:
            raise ValueError(f"Line {line_number}: label field outside a label item")

        if indent == 4:
            key, value = _split_key_value(text, line_number)
            if value == "":
                current_label[key] = []
                current_list_key = key
            else:
                current_label[key] = value
                current_list_key = None
            continue

        if indent == 6 and text.startswith("- "):
            if current_list_key is None:
                raise ValueError(f"Line {line_number}: list item without a list field")
            current_label[current_list_key].append(_parse_scalar(text[2:].strip()))
            continue

        raise ValueError(f"Line {line_number}: unsupported indentation or structure")

    return document


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    return _parse_taxonomy_yaml(path)


def load_label_specs(path: Path = DEFAULT_TAXONOMY_PATH) -> list[LabelSpec]:
    taxonomy = load_taxonomy(path)
    return [LabelSpec.from_dict(label) for label in taxonomy.get("labels", [])]


def validate_specs(specs: list[LabelSpec]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for spec in specs:
        prefix = f"{spec.label_id or '<missing label_id>'}:"
        if not spec.label_id:
            errors.append("label_id is required")
        elif not LABEL_ID_PATTERN.match(spec.label_id):
            errors.append(f"{prefix} label_id must use lowercase snake_case")
        elif spec.label_id in seen_ids:
            errors.append(f"{prefix} duplicate label_id")
        seen_ids.add(spec.label_id)

        if not spec.name:
            errors.append(f"{prefix} name is required")
        if not spec.description:
            errors.append(f"{prefix} description is required")
        if not spec.scopes:
            errors.append(f"{prefix} at least one scope is required")
        invalid_scopes = sorted(set(spec.scopes) - ALLOWED_SCOPES)
        if invalid_scopes:
            errors.append(f"{prefix} invalid scopes: {', '.join(invalid_scopes)}")
        if len(spec.scopes) != len(set(spec.scopes)):
            errors.append(f"{prefix} scopes must be unique")
        if spec.lifecycle not in ALLOWED_LIFECYCLES:
            errors.append(f"{prefix} invalid lifecycle: {spec.lifecycle}")
        if not spec.owner:
            errors.append(f"{prefix} owner is required")
        if not spec.reason:
            errors.append(f"{prefix} reason is required")
        if spec.lifecycle == "deprecated" and not (spec.replacement or spec.removal_reason):
            errors.append(f"{prefix} deprecated labels need replacement or removal_reason")
        if spec.icon and ":" not in spec.icon:
            errors.append(f"{prefix} icon should include an icon namespace, such as mdi:tag")

    if "hallway" not in seen_ids:
        errors.append("hallway label must remain in the taxonomy while it exists in live HA")

    return errors


def specs_by_id(specs: list[LabelSpec]) -> dict[str, LabelSpec]:
    return {spec.label_id: spec for spec in specs}


def load_live_export(path: Path) -> dict[str, Any]:
    if str(path) == "-":
        return normalize_live_export(json.load(sys.stdin))
    with path.open(encoding="utf-8") as file:
        return normalize_live_export(json.load(file))


def normalize_live_export(raw: dict[str, Any]) -> dict[str, Any]:
    labels = raw.get("labels", [])
    areas = raw.get("areas", [])

    if isinstance(labels, dict):
        labels = labels.get("labels", labels.get("result", []))
    if isinstance(areas, dict):
        areas = areas.get("areas", areas.get("result", []))

    return {
        "labels": sorted((label for label in labels), key=lambda label: label.get("label_id", "")),
        "areas": sorted((area for area in areas), key=lambda area: area.get("area_id", "")),
    }


def audit_live(specs: list[LabelSpec], live: dict[str, Any]) -> dict[str, Any]:
    spec_map = specs_by_id(specs)
    live_labels = {
        label["label_id"]: label
        for label in live.get("labels", [])
        if isinstance(label, dict) and label.get("label_id")
    }
    active_spec_ids = {
        spec.label_id for spec in specs if spec.lifecycle in {"active", "reserved"}
    }
    deprecated_spec_ids = {
        spec.label_id for spec in specs if spec.lifecycle == "deprecated"
    }

    field_mismatches: list[dict[str, Any]] = []
    for label_id, live_label in sorted(live_labels.items()):
        spec = spec_map.get(label_id)
        if spec is None:
            continue
        for field, expected in spec.live_fields().items():
            actual = live_label.get(field)
            if actual != expected:
                field_mismatches.append(
                    {
                        "label_id": label_id,
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    area_scope_mismatches: list[dict[str, str]] = []
    for area in live.get("areas", []):
        if not isinstance(area, dict):
            continue
        for label_id in area.get("labels", []) or []:
            spec = spec_map.get(label_id)
            if spec is None:
                area_scope_mismatches.append(
                    {
                        "area_id": str(area.get("area_id", "")),
                        "label_id": str(label_id),
                        "reason": "label is not in taxonomy",
                    }
                )
            elif "area" not in spec.scopes:
                area_scope_mismatches.append(
                    {
                        "area_id": str(area.get("area_id", "")),
                        "label_id": str(label_id),
                        "reason": "label taxonomy does not allow area scope",
                    }
                )

    return {
        "missing_labels": sorted(active_spec_ids - set(live_labels)),
        "unknown_live_labels": sorted(set(live_labels) - set(spec_map)),
        "deprecated_live_labels": sorted(set(live_labels) & deprecated_spec_ids),
        "field_mismatches": field_mismatches,
        "area_scope_mismatches": area_scope_mismatches,
        "live_label_count": len(live_labels),
        "taxonomy_label_count": len(specs),
    }


def plan_label_operations(specs: list[LabelSpec], live: dict[str, Any]) -> list[dict[str, Any]]:
    live_labels = {
        label["label_id"]: label
        for label in live.get("labels", [])
        if isinstance(label, dict) and label.get("label_id")
    }
    operations: list[dict[str, Any]] = []

    for spec in specs:
        if spec.lifecycle == "deprecated":
            continue
        live_label = live_labels.get(spec.label_id)
        if live_label is None:
            operations.append(
                {
                    "action": "create",
                    "label_id": spec.label_id,
                    "fields": spec.live_fields(),
                }
            )
            continue

        updates = {
            field: expected
            for field, expected in spec.live_fields().items()
            if live_label.get(field) != expected
        }
        if updates:
            operations.append(
                {
                    "action": "update",
                    "label_id": spec.label_id,
                    "fields": updates,
                }
            )

    return operations


class HomeAssistantWebSocket:
    def __init__(self, url: str, token: str, timeout: int = 30) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "ws", "wss"}:
            raise ValueError("HA_URL must start with http, https, ws, or wss")
        secure = parsed.scheme in {"https", "wss"}
        port = parsed.port or (443 if secure else 80)
        base_path = parsed.path.rstrip("/")
        self.host = parsed.hostname or ""
        self.path = f"{base_path}/api/websocket" if base_path else "/api/websocket"
        self.port = port
        self.secure = secure
        self.token = token
        self.timeout = timeout
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.next_id = 1

    def __enter__(self) -> "HomeAssistantWebSocket":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def connect(self) -> None:
        raw_sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.secure:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.sock = context.wrap_socket(raw_sock, server_hostname=self.host)
        else:
            self.sock = raw_sock
        self.sock.settimeout(self.timeout)
        self._handshake()
        auth_required = self.receive_json()
        if auth_required.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected auth handshake: {auth_required}")
        self.send_json({"type": "auth", "access_token": self.token})
        auth_response = self.receive_json()
        if auth_response.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant authentication failed: {auth_response}")

    def command(self, command_type: str, **payload: object) -> object:
        message_id = self.next_id
        self.next_id += 1
        self.send_json({"id": message_id, "type": command_type, **payload})
        while True:
            message = self.receive_json()
            if message.get("type") == "pong":
                continue
            if message.get("id") != message_id:
                continue
            if not message.get("success", False):
                raise RuntimeError(f"{command_type} failed: {message.get('error')}")
            return message.get("result")

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        headers = [
            f"GET {self.path} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            "",
            "",
        ]
        self._send_raw("\r\n".join(headers).encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self._recv_raw(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response[:200]!r}")

    def send_json(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, data)

    def receive_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 0x8:
                raise RuntimeError("Home Assistant closed the WebSocket connection")
            if opcode == 0x9:
                self._send_frame(0xA, payload)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        first_byte = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first_byte, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first_byte, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first_byte, 0x80 | 127, length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._send_raw(header + mask + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        header = self._recv_exact(2)
        first_byte, second_byte = header
        opcode = first_byte & 0x0F
        length = second_byte & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if second_byte & 0x80:
            mask = self._recv_exact(4)
            payload = self._recv_exact(length)
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        else:
            payload = self._recv_exact(length)
        return opcode, payload

    def _recv_exact(self, length: int) -> bytes:
        data = b""
        while len(data) < length:
            data += self._recv_raw(length - len(data))
        return data

    def _send_raw(self, payload: bytes) -> None:
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")
        self.sock.sendall(payload)

    def _recv_raw(self, length: int) -> bytes:
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")
        chunk = self.sock.recv(length)
        if not chunk:
            raise RuntimeError("WebSocket connection closed")
        return chunk


def fetch_live_from_ha() -> dict[str, Any]:
    url = os.environ.get("HA_URL")
    token = os.environ.get("HA_TOKEN")
    if not url or not token:
        raise RuntimeError("Set HA_URL and HA_TOKEN, or pass --live-json")
    with HomeAssistantWebSocket(url=url, token=token) as client:
        labels = client.command("config/label_registry/list")
        areas = client.command("config/area_registry/list")
    return normalize_live_export({"labels": labels, "areas": areas})


def apply_operations(operations: list[dict[str, Any]], specs: list[LabelSpec]) -> list[dict[str, Any]]:
    spec_map = specs_by_id(specs)
    url = os.environ.get("HA_URL")
    token = os.environ.get("HA_TOKEN")
    if not url or not token:
        raise RuntimeError("Set HA_URL and HA_TOKEN before using --execute")

    results: list[dict[str, Any]] = []
    with HomeAssistantWebSocket(url=url, token=token) as client:
        for operation in operations:
            label_id = operation["label_id"]
            spec = spec_map[label_id]
            fields = {key: value for key, value in spec.live_fields().items() if value is not None}
            if operation["action"] == "create":
                result = client.command("config/label_registry/create", **fields)
                if isinstance(result, dict) and result.get("label_id") != label_id:
                    raise RuntimeError(
                        f"Created label {result.get('label_id')!r}, expected {label_id!r}"
                    )
            elif operation["action"] == "update":
                result = client.command("config/label_registry/update", label_id=label_id, **fields)
            else:
                raise RuntimeError(f"Unsupported operation: {operation}")
            results.append({"operation": operation, "result": result})
    return results


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def command_validate(args: argparse.Namespace) -> int:
    specs = load_label_specs(args.taxonomy)
    errors = validate_specs(specs)
    print_json(
        {
            "label_count": len(specs),
            "status": "valid" if not errors else "invalid",
            "errors": errors,
        }
    )
    return 0 if not errors else 1


def command_export_live(args: argparse.Namespace) -> int:
    live = load_live_export(args.live_json) if args.live_json else fetch_live_from_ha()
    print_json(live)
    return 0


def command_audit_live(args: argparse.Namespace) -> int:
    specs = load_label_specs(args.taxonomy)
    errors = validate_specs(specs)
    if errors:
        print_json({"status": "invalid_taxonomy", "errors": errors})
        return 1
    live = load_live_export(args.live_json) if args.live_json else fetch_live_from_ha()
    print_json(audit_live(specs, live))
    return 0


def command_apply_labels(args: argparse.Namespace) -> int:
    specs = load_label_specs(args.taxonomy)
    errors = validate_specs(specs)
    if errors:
        print_json({"status": "invalid_taxonomy", "errors": errors})
        return 1
    live = load_live_export(args.live_json) if args.live_json else fetch_live_from_ha()
    operations = plan_label_operations(specs, live)
    if not args.execute:
        print_json({"dry_run": True, "operations": operations})
        return 0
    results = apply_operations(operations, specs)
    print_json({"dry_run": False, "results": results})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and reconcile HA label taxonomy.")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=DEFAULT_TAXONOMY_PATH,
        help="Path to docs/ha_label_taxonomy.yaml.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate the repo taxonomy.")
    validate.set_defaults(func=command_validate)

    export_live = subparsers.add_parser("export-live", help="Export live labels and area labels.")
    export_live.add_argument("--live-json", type=Path, help="Normalize an existing live export JSON.")
    export_live.set_defaults(func=command_export_live)

    audit_live_parser = subparsers.add_parser("audit-live", help="Compare live HA labels to taxonomy.")
    audit_live_parser.add_argument("--live-json", type=Path, help="Use an existing live export JSON.")
    audit_live_parser.set_defaults(func=command_audit_live)

    apply_labels = subparsers.add_parser(
        "apply-labels",
        help="Create/update label definitions. Dry-run unless --execute is set.",
    )
    apply_labels.add_argument("--live-json", type=Path, help="Use an existing live export JSON.")
    apply_labels.add_argument("--execute", action="store_true", help="Apply changes to live HA.")
    apply_labels.set_defaults(func=command_apply_labels)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # pragma: no cover - CLI guardrail
        print_json({"status": "error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
