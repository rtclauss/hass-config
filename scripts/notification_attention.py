"""Prepare one recipient's attention alert without changing existing delivery.

Pure configuration transform: the caller verifies the audience, saves the
original, and writes the returned config through Home Assistant's config API.
"""
from copy import deepcopy
import re


def add_recipient_attention(
    config: dict,
    *,
    recipient_service: str,
    existing_recipients: set[str],
    title: str,
    message: str,
    tag: str,
    destinations: list[tuple[str, str]],
) -> dict:
    """Add a direct alert; preserve triggers and every existing action/payload."""
    if not re.fullmatch(r"notify\.mobile_app_[a-z0-9_]+", recipient_service):
        raise ValueError("Provide one explicit Companion app notification service")
    if recipient_service in existing_recipients:
        raise ValueError("Recipient already receives this alert")
    if not title.strip() or not message.strip() or not tag.strip():
        raise ValueError("An alert needs a title, message, and incident tag")
    if not 1 <= len(destinations) <= 3:
        raise ValueError("Provide one to three review destinations")
    buttons = []
    for label, entity_id in destinations:
        if not label.strip() or not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", entity_id):
            raise ValueError("Expected a button label and a literal entity ID")
        buttons.append({"action": "URI", "title": label,
            "uri": f"/?more-info-entity-id={entity_id}"})
    result = deepcopy(config)
    key = "actions" if "actions" in result else "action"
    actions = result.get(key)
    if not isinstance(actions, list):
        raise ValueError("Expected an automation action list")
    notifications = [step for step in actions if isinstance(step, dict)
        and str(step.get("action", step.get("service", ""))).startswith("notify.")]
    if len(notifications) != 1:
        raise ValueError("Review one existing top-level notification at a time")
    payload = notifications[0].get("data", {})
    original_message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(original_message, str) or original_message in {
        "clear_notification", "request_location_update",
    } or original_message.startswith("command_"):
        raise ValueError("Original action must be an alert, not a mobile command")
    actions.insert(0, {"action": recipient_service, "continue_on_error": True,
        "data": {"title": title, "message": message, "data": {
            "tag": tag, "url": buttons[0]["uri"], "clickAction": buttons[0]["uri"],
            "actions": buttons}}})
    return result
