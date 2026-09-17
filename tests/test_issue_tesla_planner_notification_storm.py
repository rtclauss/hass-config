"""Regression test for a Tesla charge-planner notification storm.

Background: `binary_sensor.upcoming_trip_charging` is a trigger-based sensor
that recomputes roughly every 15 minutes (packages/car.yaml). Its
`distance_mi`/`duration_min` attributes come from a live Waze traffic query,
so they drift slightly (e.g. 134.43 -> 136.00 -> 134.45 mi) on every
recompute even when nothing about the plan has actually changed. Home
Assistant fires a `state_changed` event for ANY change to an entity,
including attribute-only ones, so `tesla_departure_planner_apply`'s
`trip_change` trigger (deliberately unscoped, no `attribute:` filter, so the
automation recomputes on every sensor update) also fires on every one of
those attribute-only ticks.

Before this fix, the notify choose-block's condition was
`trigger.id in ['nightly', 'trip_change'] and tesla_plan.active` — so while a
trip stayed active for hours (e.g. an evening-through-morning Visitation),
every 15-minute Waze-traffic-drift recompute re-sent the same notification,
producing roughly one notification every 15 minutes instead of one for the
actual plan change. This produced ~15 notifications overnight for a single
still-active trip.

The fix requires the `trip_change` branch to represent a genuine on/off
transition (`trigger.from_state.state != trigger.to_state.state`) rather than
just "the sensor updated," while leaving the `nightly` digest and
`early_morning` low-tire-pressure check unaffected (neither is a `state`
trigger, so neither has a `from_state`/`to_state` to compare).
"""

from __future__ import annotations

import re
from pathlib import Path


CAR_PATH = Path(__file__).resolve().parents[1] / "packages" / "car.yaml"


def _automation_block(automation_id: str) -> str:
    text = CAR_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_trip_change_notification_requires_a_genuine_state_transition() -> None:
    block = _automation_block("tesla_departure_planner_apply")

    assert "trigger.id in ['nightly', 'trip_change']" not in block

    assert "{{ trigger.id == 'nightly' and tesla_plan.active }}" in block
    assert (
        "{{ trigger.id == 'early_morning' and tesla_plan.precondition and tesla_plan.low_tpms }}"
        in block
    )

    trip_change_condition = re.search(
        r"trigger\.id == 'trip_change' and tesla_plan\.active and\n\s*"
        r"trigger\.from_state is not none and\n\s*"
        r"trigger\.to_state is not none and\n\s*"
        r"trigger\.from_state\.state in \['on', 'off'\] and\n\s*"
        r"trigger\.to_state\.state in \['on', 'off'\] and\n\s*"
        r"trigger\.from_state\.state != trigger\.to_state\.state",
        block,
    )
    assert trip_change_condition is not None, (
        "trip_change notification must gate on a real on/off transition, "
        "not just any recompute of the sensor"
    )


def test_trip_change_notification_ignores_unavailable_recovery() -> None:
    # A transient unavailable/unknown blip (HA restart, template reload) that
    # recovers straight to "on" must not read as a fresh activation just
    # because from_state.state != to_state.state — both sides must be a real
    # on/off value.
    block = _automation_block("tesla_departure_planner_apply")

    assert "trigger.from_state.state in ['on', 'off']" in block
    assert "trigger.to_state.state in ['on', 'off']" in block


def test_trip_change_trigger_itself_stays_unscoped() -> None:
    # The trigger must keep reacting to every sensor update (so the
    # automation recomputes charge limit / precondition promptly) — only the
    # *notification* condition should filter out attribute-only wobble.
    block = _automation_block("tesla_departure_planner_apply")
    trigger_section = block.split("    trigger:\n", 1)[1].split("    condition:", 1)[0]

    trip_change_trigger = re.search(
        r"- trigger: state\n\s*entity_id: binary_sensor\.upcoming_trip_charging\n\s*id: trip_change",
        trigger_section,
    )
    assert trip_change_trigger is not None
