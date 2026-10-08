from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
DESK_PACKAGE = ROOT / "packages" / "desk.yaml"
OFFICE_TILE = ROOT / "lovelace" / "tiles" / "tiles_office.yaml"
MUSHROOM_DASHBOARD = ROOT / ".storage" / "lovelace.ryan_new_mushroom"

NATIVE_DESK_BUTTONS = {
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

AUTO_DESK_WRAPPERS = {
    "uplift_desk_auto_move_preset_1": "button.uplift_desk_75b205_move_to_preset_1",
    "uplift_desk_auto_move_preset_2": "button.uplift_desk_75b205_move_to_preset_2",
}


def _script_block(script_id: str) -> str:
    lines = DESK_PACKAGE.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def test_desk_package_uses_native_uplift_component_buttons() -> None:
    text = DESK_PACKAGE.read_text(encoding="utf-8")

    for entity_id in NATIVE_DESK_BUTTONS:
        assert entity_id in text

    assert "shell_command.uplift_desk" not in text
    assert "uplift_ble_remote.sh" not in text
    assert "number.uplift_desk_75b205_height_setpoint" in text
    for limit in ("max", "min"):
        assert f"button.uplift_desk_75b205_move_to_{limit}_height" not in text


def test_office_dashboards_use_manual_desk_script_wrappers() -> None:
    for path in (OFFICE_TILE, MUSHROOM_DASHBOARD):
        text = path.read_text(encoding="utf-8")

        for entity_id in MANUAL_DESK_SCRIPTS:
            assert entity_id in text

        assert "service: button.press" not in text
        assert '"service": "button.press"' not in text
        assert "button.uplift_desk_75b205_move_to_" not in text
        assert "button.uplift_desk_75b205_stop" not in text


def test_auto_desk_wrappers_share_motion_guard() -> None:
    shared = _script_block("uplift_desk_auto_move")

    assert "entity_id: timer.uplift_desk_motion_window" in shared
    assert 'state: "idle"' in shared
    assert "action: button.press" in shared
    assert 'entity_id: "{{ target_button }}"' in shared
    assert "action: timer.start" in shared
    assert shared.count("timer.uplift_desk_motion_window") == 2

    for script_id, target_button in AUTO_DESK_WRAPPERS.items():
        block = _script_block(script_id)

        assert "action: script.uplift_desk_auto_move" in block
        assert f"target_button: {target_button}" in block
        assert "timer.uplift_desk_motion_window" not in block
        assert "action: button.press" not in block

    maximum = _script_block("uplift_desk_auto_move_max")
    assert "action: script.uplift_desk_auto_move" in maximum
    assert "height_limit: max" in maximum


@pytest.mark.parametrize("limit,target", [("min", 643), ("max", 1293)])
@pytest.mark.parametrize("bounds,state,allowed", [
    ((500, 1300), "unknown", True),
    ((500, 1300), "unavailable", False),
    ((700, 1200), "unknown", False),
    ((None, None), "unknown", False),
])
def test_height_targets_respect_availability_and_bounds(limit, target, bounds, state, allowed):
    scripts = yaml.safe_load(DESK_PACKAGE.read_text())["script"]
    sequence = scripts["uplift_desk_move_to_limit"]["sequence"]
    env = Environment(undefined=StrictUndefined)
    rendered = env.from_string(sequence[0]["variables"]["target_mm"]).render(height_limit=limit)
    assert int(rendered) == target
    valid = env.from_string(sequence[1]["value_template"]).render(
        height_limit=limit, target_mm=target,
        states=lambda _: state,
        state_attr=lambda _, key: dict(zip(("min", "max"), bounds))[key],
    )
    assert (valid == "True") is allowed
    assert sequence[2]["action"] == "number.set_value"
    assert env.from_string(sequence[2]["data"]["value"]).render(target_mm=target) == str(target)
    manual = scripts[f"uplift_desk_manual_move_{limit}"]["sequence"]
    assert manual == [{"action": "script.uplift_desk_move_to_limit", "data": {"height_limit": limit}}]


def test_invalid_height_limit_is_rejected():
    sequence = yaml.safe_load(DESK_PACKAGE.read_text())["script"]["uplift_desk_move_to_limit"]["sequence"]
    result = Environment(undefined=StrictUndefined).from_string(sequence[1]["value_template"]).render(
        height_limit="invalid", target_mm=643,
    )
    assert result == "False"
