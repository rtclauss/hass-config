from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
ADAPTIVE_LIGHTING_PATH = ROOT / "packages" / "adaptive_lighting.yaml"
OWNER_SUITE_SWITCHES = (
    "switch.adaptive_lighting_owner_suite",
    "switch.adaptive_lighting_owner_suite_bed_strip",
)
RESET_KEY = "reset_manual_control_on_sleep_mode_change"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


def _wake_ramp_steps() -> list[dict]:
    script = _load(WORKDAY_PATH)["script"]["owner_suite_morning_transition"]
    parallel = next(step["parallel"] for step in script["sequence"] if "parallel" in step)
    return parallel[0]["sequence"]


def _index(steps: list[dict], predicate) -> int:
    matches = [i for i, step in enumerate(steps) if predicate(step)]
    assert len(matches) == 1, matches
    return matches[0]


def _lock(switch: str, manual_control: bool):
    return lambda step: (
        step.get("action") == "adaptive_lighting.set_manual_control"
        and step["data"]["entity_id"] == switch
        and step["data"]["manual_control"] is manual_control
    )


def _reset_on_sleep_change(switch: str, value: bool):
    return lambda step: (
        step.get("action") == "adaptive_lighting.change_switch_settings"
        and step["data"]["entity_id"] == switch
        and step["data"].get(RESET_KEY) is value
    )


def test_wake_ramp_keeps_manual_control_locked_across_sleep_mode_change() -> None:
    # Issue #1210: turning sleep mode off made Adaptive Lighting clear the lock
    # and force a 2s jump to the daytime target before the 180s ramp started.
    steps = _wake_ramp_steps()
    sleep_off = _index(
        steps,
        lambda step: step.get("action") == "switch.turn_off"
        and step["data"]["entity_id"] == ["switch.sleep_mode"],
    )
    ramp_delay = _index(steps, lambda step: step.get("delay") == {"seconds": 180})

    for switch in OWNER_SUITE_SWITCHES:
        lock = _index(steps, _lock(switch, True))
        keep = _index(steps, _reset_on_sleep_change(switch, False))
        restore = _index(steps, _reset_on_sleep_change(switch, True))
        unlock = _index(steps, _lock(switch, False))

        assert lock < keep < sleep_off < ramp_delay < restore < unlock


def test_reconcile_pins_owner_suite_reset_on_sleep_mode_change() -> None:
    # A wake ramp interrupted mid-way must not leave the reset disabled past
    # the next Home Assistant restart.
    automation = next(
        a
        for a in _load(ADAPTIVE_LIGHTING_PATH)["automation"]
        if a["id"] == "reconcile_owner_suite_adaptive_lighting"
    )
    settings = {
        step["data"]["entity_id"]: step["data"]
        for step in automation["action"]
        if step.get("action") == "adaptive_lighting.change_switch_settings"
    }

    for switch in OWNER_SUITE_SWITCHES:
        assert settings[switch][RESET_KEY] is True
