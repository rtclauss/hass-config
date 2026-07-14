from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "fermentor.yaml"
DASHBOARD_PATH = ROOT / ".storage" / "lovelace.ryan_new_mushroom"


def test_fermentor_reboot_uses_restricted_noninteractive_ssh() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "reboot_fermentor:" in text
    assert "action: shell_command.reboot_fermentor" in text
    assert "-o BatchMode=yes" in text
    assert "-o StrictHostKeyChecking=yes" in text
    assert "-F /config/.ssh/config" in text
    assert '"sudo -n /usr/bin/systemctl reboot"' in text
    assert "StrictHostKeyChecking=no" not in text


def test_testing_dashboard_has_confirmed_fermentor_reboot_button() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    testing_view = next(
        view
        for view in dashboard["data"]["config"]["views"]
        if view.get("path") == "testing"
    )
    reboot_card = next(
        card
        for card in testing_view["cards"]
        if card.get("entity") == "script.reboot_fermentor"
    )

    assert reboot_card["name"] == "Reboot Fermentor"
    assert reboot_card["icon"] == "mdi:restart-alert"
    assert reboot_card["tap_action"] == {
        "action": "call-service",
        "service": "script.turn_on",
        "target": {"entity_id": "script.reboot_fermentor"},
        "confirmation": {
            "text": "Reboot fermentor? Services hosted there will be briefly unavailable."
        },
    }
