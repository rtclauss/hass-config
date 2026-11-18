"""An away-triggered X40 clean must not start after the owner is home (issue #1213).

Every main-level clean funnels into one serialized dispatcher
(`script.x40_ultra_main_level_policy_clean`, `mode: queued`), so a request made
on departure can sit in the queue behind an in-flight run and be dequeued much
later. The dispatcher already re-reads presence at dequeue time and drops the
request when `require_away` is set -- but only the launchers that opt in.

Observed 2026-11-18: a 487 ms Bayesian presence flap emitted a spurious
departure while the owner was arriving. `vacuum_leave_home` queued a full-floor
request at 19:06:09Z; presence recovered 36 s later; the request was dequeued at
19:44:39Z and started a vacuum+mop cycle with the owner home. `vacuum_return_home`
calls only `vacuum.return_to_base`, which docks the robot but neither cancels nor
drains the queue -- and because the dispatcher's entry gate requires the robot to
be `docked`/`idle`, docking it on arrival is what admitted the queued run.

`tests/test_pre_arrival_clean.py` covers the dispatcher side (the drop itself and
the field plumbing). These tests cover the launchers.
"""

from __future__ import annotations

import re
from pathlib import Path

from privacy_ids import PRESENCE_SLUG, PRESENCE_TRACKER


ROOT = Path(__file__).resolve().parents[1]

ZONE_PATH = ROOT / "packages" / "zone.yaml"
CURLING_PATH = ROOT / "packages" / "curling.yaml"
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"

MAIN_LEVEL_LAUNCHERS = (
    "action: script.vacuum_main_and_upstairs_levels",
    "action: script.vacuum_main_level_full_floor",
)

# Call sites that deliberately do NOT require the owner to be away, with the
# reason each one is exempt. Anything else that launches a main-level clean from
# a departure must set require_away, which the sweep below enforces.
EXEMPT_AUTOMATIONS = {
    # Fires at 13:00 specifically BECAUSE the owner has been home for days.
    "x40_ultra_maintenance_clean_after_four_home_days": "runs deliberately while home",
    # Mixed triggers: a work-zone leave, but also a manual VACUUM_HOUSE action
    # from the phone, which must still run when the owner is home. Splitting the
    # two paths is follow-up work on #1213, not a blanket require_away.
    "vacuum_while_working": "shares a manual notification-action trigger",
}


def _automation_blocks(path: Path) -> dict[str, str]:
    """Map automation id -> its YAML block, for the automations in one package."""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not line.startswith("  - "):
            continue
        # The id may be on the `- ` line itself or on a following key line.
        for candidate in range(index, min(index + 12, len(lines))):
            if candidate > index and lines[candidate].startswith("  - "):
                break
            match = re.match(r"^\s*(?:- )?id: (\S+)\s*$", lines[candidate])
            if match:
                starts.append((index, match.group(1)))
                break

    blocks: dict[str, str] = {}
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        for index in range(start + 1, end):
            if lines[index] and not lines[index].startswith(" "):
                end = min(end, index)
                break
        blocks[name] = "\n".join(lines[start:end])
    return blocks


def _is_away_triggered(block: str) -> bool:
    trigger_section = block.split("    trigger:", 1)
    if len(trigger_section) == 1:
        return False
    triggers = trigger_section[1].split("    condition:", 1)[0].split("    action:", 1)[0]
    leaves_home_zone = (
        "event: leave" in triggers
        and "zone: zone.home" in triggers
        and PRESENCE_TRACKER in triggers
    )
    return leaves_home_zone or f"event_type: {PRESENCE_SLUG}_departure" in triggers


def _launcher_call(block: str) -> str:
    """The main-level launcher call and whatever is indented under it."""
    for marker in MAIN_LEVEL_LAUNCHERS:
        if marker not in block:
            continue
        lines = block.splitlines()
        start = next(i for i, line in enumerate(lines) if marker in line)
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = len(lines)
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                end = index
                break
        return "\n".join(lines[start:end])
    raise AssertionError("block does not launch a main-level clean")


def test_departure_launcher_requires_the_owner_to_still_be_away() -> None:
    block = _automation_blocks(ZONE_PATH)["vacuum_leave_home"]

    assert "require_away: true" in _launcher_call(block), (
        "a departure-queued main-level clean can start after the owner is home"
    )


def test_curling_departure_launcher_requires_the_owner_to_still_be_away() -> None:
    block = _automation_blocks(CURLING_PATH)["leave_home_for_curling"]

    assert "require_away: true" in _launcher_call(block)


def test_departure_launcher_does_not_expire_its_request() -> None:
    # Deliberate: unlike the time-of-day litter pass, a departure clean is still
    # wanted whenever it dequeues provided the house is still empty, and
    # require_away is exactly that test. Pinned so an expiry is not added
    # without revisiting the reasoning in #1213.
    call = _launcher_call(_automation_blocks(ZONE_PATH)["vacuum_leave_home"])

    assert "expires_at" not in call


def test_departure_den_start_is_not_gated_on_the_x40_queue() -> None:
    # The den is a different robot reached through vacuum.start, with no queue to
    # go stale in, so it takes no require_away. The arrival path docks it.
    block = _automation_blocks(ZONE_PATH)["vacuum_leave_home"]

    assert "action: script.vacuum_den_guarded_start" in block
    den = block.split("action: script.vacuum_den_guarded_start", 1)[1]
    assert "require_away" not in den


def test_every_away_triggered_main_level_launch_requires_away() -> None:
    # Standing guard: a new launcher wired to a departure must opt in, or be
    # added to EXEMPT_AUTOMATIONS with a stated reason.
    missing = []
    checked = 0
    for path in (ZONE_PATH, CURLING_PATH, WORKDAY_PATH, TRIPS_PATH, VACUUM_PATH):
        for name, block in _automation_blocks(path).items():
            if not any(marker in block for marker in MAIN_LEVEL_LAUNCHERS):
                continue
            if name in EXEMPT_AUTOMATIONS or not _is_away_triggered(block):
                continue
            checked += 1
            if "require_away: true" not in _launcher_call(block):
                missing.append(f"{path.name}:{name}")

    assert not missing, f"away-triggered launches without require_away: {missing}"
    # Guard the guard: if the detection stops matching anything, the sweep above
    # would pass vacuously.
    assert checked >= 2, f"expected to check at least the two departure launchers, saw {checked}"
