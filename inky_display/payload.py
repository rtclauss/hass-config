from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_DISPLAY_IDS = {"owner_suite", "office"}
SUPPORTED_MODES = {
    "owner_suite": {"night_preview", "morning", "up_for_day", "midday"},
    "office": {"focus", "home_arrival", "midday", "guest_info"},
}
SUPPORTED_ACCENTS = {"red", "yellow", "black"}
SUPPORTED_LEVELS = {"normal", "emphasis", "urgent"}
MAX_ROWS = 4
MAX_TEXT_LENGTH = 48
VOLATILE_UPDATE_FOOTER = re.compile(r"^Updated \d{2}:\d{2}$")
# Distinct from any real footer text (including "") so that clearing the
# footer after a volatile timestamp is never mistaken for a duplicate.
_VOLATILE_FOOTER_SENTINEL = "\x00volatile-footer\x00"


@dataclass(frozen=True)
class DisplayPayload:
    schema_version: int
    display_id: str
    mode: str
    accent: str
    title: str
    subtitle: str
    sections: tuple[dict[str, Any], ...]
    footer: str


def validate_payload(data: dict[str, Any]) -> DisplayPayload:
    schema_version = int(data.get("schema_version", SUPPORTED_SCHEMA_VERSION))
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {schema_version}")

    display_id = _required_text(data, "display_id")
    if display_id not in SUPPORTED_DISPLAY_IDS:
        raise ValueError(f"Unsupported display_id: {display_id}")

    mode = _required_text(data, "mode")
    if mode not in SUPPORTED_MODES[display_id]:
        raise ValueError(f"Unsupported mode for {display_id}: {mode}")

    accent = _text(data.get("accent", "red"))
    if accent not in SUPPORTED_ACCENTS:
        raise ValueError(f"Unsupported accent: {accent}")

    sections = tuple(_normalize_sections(data.get("sections", [])))
    return DisplayPayload(
        schema_version=schema_version,
        display_id=display_id,
        mode=mode,
        accent=accent,
        title=_clip(_text(data.get("title", ""))),
        subtitle=_clip(_text(data.get("subtitle", ""))),
        sections=sections,
        footer=_clip(_text(data.get("footer", ""))),
    )


def payload_hash(payload: DisplayPayload) -> str:
    # Suppress only the publisher's volatile timestamp. Other footer text is
    # guest-facing display content and must participate in duplicate detection.
    # A sentinel (not "") stands in for the timestamp so an omitted/blank
    # footer remains distinguishable from a suppressed one — otherwise
    # clearing the footer after a timestamp was rendered would hash the same
    # as no change at all, leaving the stale timestamp on the panel forever.
    semantic_footer = (
        _VOLATILE_FOOTER_SENTINEL
        if VOLATILE_UPDATE_FOOTER.fullmatch(payload.footer)
        else payload.footer
    )
    canonical = json.dumps(
        {
            "schema_version": payload.schema_version,
            "display_id": payload.display_id,
            "mode": payload.mode,
            "accent": payload.accent,
            "title": payload.title,
            "subtitle": payload.subtitle,
            "sections": payload.sections,
            "footer": semantic_footer,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_sections(sections: Any) -> list[dict[str, Any]]:
    if not isinstance(sections, list):
        return []

    normalized: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("type") != "rows":
            continue
        rows = section.get("rows", [])
        if not isinstance(rows, list):
            continue
        normalized.append(
            {
                "type": "rows",
                "rows": tuple(_normalize_rows(rows[:MAX_ROWS])),
            }
        )
    return normalized


def _normalize_rows(rows: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = _text(row.get("level", "normal"))
        if level not in SUPPORTED_LEVELS:
            level = "normal"
        normalized.append(
            {
                "label": _clip(_text(row.get("label", "")), 18),
                "value": _clip(_text(row.get("value", "")), 28),
                "level": level,
                "icon": _clip(_normalize_icon(row.get("icon", "")), 32),
            }
        )
    return normalized


def _required_text(data: dict[str, Any], key: str) -> str:
    value = _text(data.get(key, ""))
    if value == "":
        raise ValueError(f"Missing required field: {key}")
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_icon(value: Any) -> str:
    icon = _text(value)
    if icon == "":
        return ""
    if icon.startswith("mdi:"):
        return icon
    return f"mdi:{icon}"


def _clip(value: str, limit: int = MAX_TEXT_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
