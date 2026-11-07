"""Build narrow JSON patches for retired controls on an exported HA dashboard.

Apply through the dashboard API with its fresh configuration hash. Removed user
IDs come from the live repair report and must stay out of committed fixtures.
"""
from __future__ import annotations


def repair_patches(config: dict, removed_users: set[str]) -> list[dict]:
    patches = []
    for view_index, view in enumerate(config.get("views", [])):
        visible = view.get("visible")
        if isinstance(visible, list):
            retained = [item for item in visible if item.get("user") not in removed_users]
            if retained != visible:
                # An orphan-only allowlist currently hides this tab from everyone.
                # Preserve that visibility instead of accidentally exposing it.
                patches.append({"op": "replace", "path": f"/views/{view_index}/visible",
                                "value": retained or False})
        if view.get("path") != "cleaning-v2":
            continue
        for section_index, section in enumerate(view.get("sections", [])):
            if not any(card.get("heading") == "Cat-Safe Cleaning Policy"
                       for card in section.get("cards", [])):
                continue
            patches.append({
                "op": "replace", "path": f"/views/{view_index}/sections/{section_index}/cards",
                "value": [
                    {"type": "heading", "heading": "Cleaning controls", "heading_style": "title"},
                    {"type": "markdown", "content": "Guest mode and active trip guest visits prevent cleaning. Den cleaning also requires its doors confirmed closed."},
                    {"type": "shortcut", "label": "Clean all floors", "icon": "mdi:broom",
                     "tap_action": {"action": "perform-action", "perform_action": "script.vacuum_manual_start",
                                    "data": {"robot": "all"}}},
                    {"type": "shortcut", "label": "Dock all robots", "icon": "mdi:robot-vacuum",
                     "tap_action": {"action": "perform-action", "perform_action": "script.vacuum_dock_all_robots"}},
                ],
            })
    return patches
