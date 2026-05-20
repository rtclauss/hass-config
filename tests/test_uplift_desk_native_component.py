from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESK_PACKAGE = ROOT / "packages" / "desk.yaml"
OFFICE_TILE = ROOT / "lovelace" / "tiles" / "tiles_office.yaml"
MUSHROOM_DASHBOARD = ROOT / ".storage" / "lovelace.ryan_new_mushroom"

NATIVE_DESK_BUTTONS = {
    "button.uplift_desk_75b205_move_to_max_height",
    "button.uplift_desk_75b205_move_to_min_height",
    "button.uplift_desk_75b205_move_to_preset_1",
    "button.uplift_desk_75b205_move_to_preset_2",
    "button.uplift_desk_75b205_stop",
}

MANUAL_DESK_SCRIPTS = {
    "script.uplift_desk_manual_move_max",
    "script.uplift_desk_manual_move_min",
    "script.uplift_desk_manual_move_preset_1",
    "script.uplift_desk_manual_move_preset_2",
    "script.uplift_desk_manual_stop",
}


def test_desk_package_uses_native_uplift_component_buttons() -> None:
    text = DESK_PACKAGE.read_text(encoding="utf-8")

    for entity_id in NATIVE_DESK_BUTTONS:
        assert entity_id in text

    assert "shell_command.uplift_desk" not in text
    assert "uplift_ble_remote.sh" not in text


def test_office_dashboards_use_manual_desk_script_wrappers() -> None:
    for path in (OFFICE_TILE, MUSHROOM_DASHBOARD):
        text = path.read_text(encoding="utf-8")

        for entity_id in MANUAL_DESK_SCRIPTS:
            assert entity_id in text

        assert "service: button.press" not in text
        assert '"service": "button.press"' not in text
        assert "button.uplift_desk_75b205_move_to_" not in text
        assert "button.uplift_desk_75b205_stop" not in text
