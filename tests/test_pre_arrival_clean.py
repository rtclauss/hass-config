"""The flying-home clean must FINISH a buffer (default 30 min) before the plane lands.

In a prior trip the clean was started at takeoff, but a full vacuum+mop cycle (182-191 min)
is longer than the 150 min flight, and two more requests stacked behind it in the single
X40 queue and ran after the owner got home. These tests pin the fix: the clean is anchored
to the flight's ARRIVAL, flying-home days don't stack other launches, and queued requests
are re-validated when they are dequeued.
"""

from __future__ import annotations

from privacy_ids import HOME_CODE_LIST, PRESENCE_SENSOR

from pathlib import Path

import jinja2
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
TRIPS_PATH = ROOT / "packages" / "trips.yaml"
VACUUM_PATH = ROOT / "packages" / "xiaomi_robot_vacuum.yaml"


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
            continue
        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break
    return "\n".join(lines[start:end])


def _script_block(path: Path, script_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    target = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == target:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script {script_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            end = index
            break
    return "\n".join(lines[start:end])


def _helper_block(text: str, name: str) -> str:
    """The indented body of `  name:` under a helper section."""
    head = f"\n  {name}:\n"
    assert head in text, f"helper {name!r} not found"
    lines = []
    for line in text.split(head, 1)[1].splitlines():
        # The helper's body is every following line indented deeper than its key.
        if line.strip() and not line.startswith("    "):
            break
        lines.append(line)
    return "\n".join(lines)


# --- helpers / sensors ------------------------------------------------------------


def test_lead_time_helper_is_calibrated_above_the_worst_observed_cycle() -> None:
    helper = _helper_block(TRIPS_PATH.read_text(encoding="utf-8"), "pre_arrival_clean_lead_minutes")

    # 2026-08-01..10-29 history: X40 two-pass cycle 175-191 min (the critical path;
    # upstairs <=72 and den <=30 run in parallel). 240 = 191 + 30 min buffer + margin.
    assert "initial: 240" in helper
    assert "min: 120" in helper
    assert "max: 360" in helper


def test_finish_buffer_helper_defaults_to_thirty_minutes_before_landing() -> None:
    helper = _helper_block(TRIPS_PATH.read_text(encoding="utf-8"), "pre_arrival_clean_buffer_minutes")

    assert "initial: 30" in helper
    assert "min: 0" in helper


def test_lead_leaves_a_full_worst_case_cycle_inside_the_buffer() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")
    lead = int(_helper_block(text, "pre_arrival_clean_lead_minutes").split("initial: ", 1)[1].split()[0])
    buffer = int(_helper_block(text, "pre_arrival_clean_buffer_minutes").split("initial: ", 1)[1].split()[0])

    # Worst measured two-pass X40 cycle is 191 min; the scheduled start must still
    # clear the "full" bar of 195 min against the finish-by deadline.
    assert lead - buffer >= 195


def test_finish_by_sensor_is_arrival_minus_the_buffer_helper() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")
    block = text.split("name: Pre-Arrival Clean Finish By", 1)[1].split("\n  - ", 1)[0]

    assert "device_class: timestamp" in block
    assert "sensor.next_flight_home_arrival" in block
    assert "input_number.pre_arrival_clean_buffer_minutes" in block
    assert "availability:" in block


def test_done_for_helper_is_a_date_time_run_once_guard() -> None:
    helper = _helper_block(TRIPS_PATH.read_text(encoding="utf-8"), "pre_arrival_clean_done_for")

    assert "has_date: true" in helper
    assert "has_time: true" in helper


def test_arrival_sensor_reads_both_flight_sensors_end_time() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")
    block = text.split("name: Next Flight Home Arrival", 1)[1].split("name: Pre-Arrival Clean Start", 1)[0]

    assert "device_class: timestamp" in block
    assert f"binary_sensor.flight_to_{HOME_CODE_LIST[0].lower()}_today" in block
    assert f"binary_sensor.flight_to_{HOME_CODE_LIST[1].lower()}_today" in block
    assert "state_attr(ent, 'end_time')" in block
    # Only a flight that has not landed yet, and the soonest of them.
    assert "as_timestamp(dt) > as_timestamp(now())" in block
    assert "as_timestamp(dt) < as_timestamp(ns.best)" in block


def test_start_sensor_is_arrival_minus_the_lead_helper() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")
    block = text.split("name: Pre-Arrival Clean Start", 1)[1].split("\n  - ", 1)[0]

    assert "device_class: timestamp" in block
    assert "sensor.next_flight_home_arrival" in block
    assert "input_number.pre_arrival_clean_lead_minutes" in block
    assert "timedelta(minutes=" in block
    # The time trigger needs a valid timestamp, so the sensor is unavailable without a flight.
    assert "availability:" in block


def test_clean_day_sensor_covers_landing_start_and_recent_launch() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")
    block = text.split("default_entity_id: binary_sensor.pre_arrival_clean_day", 1)[1].split(
        "\n  - ", 1
    )[0]

    assert "sensor.next_flight_home_arrival" in block
    assert "sensor.pre_arrival_clean_start" in block
    assert "input_datetime.pre_arrival_clean_done_for" in block
    assert "== today" in block
    assert "12 * 3600" in block


# --- vacuum_flying_home -----------------------------------------------------------


def test_flying_home_is_anchored_to_landing_not_takeoff() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_flying_home")
    # Only the trigger section: the description (rightly) mentions the old takeoff trigger.
    triggers = block.split("    trigger:", 1)[1].split("    condition:", 1)[0]

    assert "at: sensor.pre_arrival_clean_start" in triggers
    # Catch-ups: itinerary appears/moves late, or Home Assistant restarts.
    assert "entity_id: sensor.pre_arrival_clean_start" in triggers
    assert "trigger: homeassistant" in triggers
    # The takeoff trigger is gone: it finished the 2026-10-09 clean 49 min after landing.
    assert "binary_sensor.flying_home_today" not in triggers


def test_flying_home_keeps_all_existing_safety_conditions() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_flying_home")
    conditions = block.split("    condition:", 1)[1].split("    action:", 1)[0]

    for entity, state in (
        ("input_boolean.trip", "on"),
        (PRESENCE_SENSOR, "off"),
        ("input_boolean.guest_mode", "off"),
        ("input_boolean.trip_guest_visit_active", "off"),
    ):
        assert f"entity_id: {entity}" in conditions
        assert f'state: "{state}"' in conditions


def test_flying_home_launches_once_per_landing() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_flying_home")
    conditions = block.split("    condition:", 1)[1].split("    action:", 1)[0]
    action = block.split("    action:", 1)[1]

    assert "input_datetime.pre_arrival_clean_done_for" in conditions
    assert ">= 6 * 3600" in conditions
    # The landing is recorded BEFORE anything launches, so a retrigger can't double-run
    # and the skip path doesn't re-notify.
    record = action.index("action: input_datetime.set_datetime")
    launch = action.index("action: script.trip_vacuum_main_and_upstairs_levels")
    skip = action.index("default:")
    assert record < launch < skip


def test_flying_home_degrades_to_vacuum_only_then_skips() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_flying_home")
    action = block.split("    action:", 1)[1]

    # Time left is measured to the finish-by deadline (landing - buffer), not landing.
    assert "finish_ts: \"{{ arrival_ts - buffer_min * 60 }}\"" in action
    assert "remaining_min: \"{{ ((finish_ts - as_timestamp(now())) / 60) | round(0) }}\"" in action
    # Enough time for a whole cycle -> full cycle with a forced mop. The bar is the
    # worst observed cycle (195 min), or the lead's cycle budget minus 5 min of trigger
    # jitter if the lead was set lower, so the scheduled start is always "full" and a
    # catch-up a few minutes late (e.g. an HA restart) still gets its mop.
    assert 'full_min: "{{ [lead_min - buffer_min - 5, 195] | min }}"' in action
    assert "remaining_min >= full_min" in action
    # Otherwise vacuum-only while a ~85 min vacuum pass still fits, otherwise skip.
    assert "vacuum_only_min: 100" in action
    assert "remaining_min >= vacuum_only_min" in action

    full = action.split("plan == 'full'", 1)[1].split("plan == 'vacuum'", 1)[0]
    assert "force_mop: true" in full
    assert "allow_mop" not in full
    assert "expires_at: \"{{ finish_iso }}\"" in full
    assert "script.pre_arrival_confirm_secondary_robots" in full

    vacuum = action.split("plan == 'vacuum'", 1)[1].split("default:", 1)[0]
    assert "force_mop: false" in vacuum
    assert "allow_mop: false" in vacuum
    assert "expires_at: \"{{ finish_iso }}\"" in vacuum
    assert "script.pre_arrival_confirm_secondary_robots" in vacuum

    skipped = action.split("default:", 1)[1]
    assert f"action: notify.all" in skipped
    assert "script.trip_vacuum_main_and_upstairs_levels" not in skipped


def test_flying_home_requests_are_dropped_if_owner_is_home_or_after_landing() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_flying_home")

    assert block.count("require_away: true") == 2  # full + vacuum-only launches
    # A request still queued at the finish-by deadline is dropped, not run late.
    assert block.count("expires_at: \"{{ finish_iso }}\"") == 2


# --- other launchers don't stack on a flying-home day ------------------------------


def test_daily_trip_clean_skips_on_a_flying_home_day_and_expires_in_queue() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_on_trip")
    conditions = block.split("    condition:", 1)[1].split("    action:", 1)[0]
    action = block.split("    action:", 1)[1]

    assert "binary_sensor.pre_arrival_clean_day" in conditions
    # `not on`, so an unavailable helper never stops the ordinary daily trip clean.
    assert "not is_state('binary_sensor.pre_arrival_clean_day', 'on')" in conditions
    assert "require_away: true" in action
    assert "timedelta(hours=2)" in action


def test_litter_pass_skips_flying_home_days_and_expires_in_queue() -> None:
    block = _automation_block(VACUUM_PATH, "vacuum_laundry_room_daily_litter")
    conditions = block.split("    condition:", 1)[1].split("    action:", 1)[0]
    action = block.split("    action:", 1)[1]

    assert "not is_state('binary_sensor.pre_arrival_clean_day', 'on')" in conditions
    assert "timedelta(hours=2)" in action
    # Unchanged behaviour: still the same 3-pass utility-room segment.
    assert "segments: 6" in action
    assert "repeats: 3" in action


# --- request fields are plumbed end to end -----------------------------------------


def test_new_request_fields_flow_from_trip_script_to_the_dispatcher() -> None:
    chain = (
        (TRIPS_PATH, "trip_vacuum_main_and_upstairs_levels"),
        (VACUUM_PATH, "vacuum_main_and_upstairs_levels"),
        (VACUUM_PATH, "vacuum_main_level_full_floor"),
        (VACUUM_PATH, "x40_ultra_main_level_policy_clean"),
    )
    for path, script_id in chain:
        block = _script_block(path, script_id)
        fields = block.split("    sequence:", 1)[0]
        for field in ("allow_mop:", "require_away:", "expires_at:"):
            assert field in fields, f"{script_id} must declare {field}"

    # Each hop forwards all three to the next.
    for path, script_id in chain[:2]:
        sequence = _script_block(path, script_id).split("    sequence:", 1)[1]
        for field in ("allow_mop:", "require_away:", "expires_at:"):
            assert field in sequence

    launcher = _script_block(VACUUM_PATH, "vacuum_main_level_full_floor").split("    sequence:", 1)[1]
    turn_on = launcher.index("action: script.turn_on")
    assert "variables:" in launcher[turn_on:]
    for field in ("allow_mop:", "require_away:", "expires_at:"):
        assert field in launcher[turn_on:]


def test_vacuum_only_request_does_not_leave_a_mop_owed() -> None:
    launcher = _script_block(VACUUM_PATH, "vacuum_main_level_full_floor").split("    sequence:", 1)[1]
    latch = launcher.split("input_boolean.x40_ultra_mop_pass_pending", 1)[0]

    # The mop-owed latch is only set when a mop is forced AND allowed.
    assert "force_mop" in latch
    assert "allow_mop" in latch


# --- dispatcher re-validates a request when it is dequeued -------------------------


def test_dispatcher_decides_when_dequeued_not_when_queued() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    header, sequence = block.split("    sequence:", 1)

    # Script-level `variables:` render at INVOCATION, so a request queued behind a long
    # run carried a stale mop_due and re-mopped right after a mop finished (2026-10-09).
    assert "\n    variables:" not in header
    assert sequence.lstrip().startswith("# Evaluate") or "- variables:" in sequence.split("- if:", 1)[0]
    assert "mop_due:" in sequence.split("- if:", 1)[0]
    assert "last_mopped_timestamp:" in sequence.split("- if:", 1)[0]


def test_dispatcher_mop_decision_honours_allow_mop() -> None:
    sequence = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean").split(
        "    sequence:", 1
    )[1]
    mop_due = sequence.split("mop_due:", 1)[1].split("request_expired:", 1)[0]

    assert "allow_mop | default(true) | bool" in mop_due
    assert "x40_ultra_mop_pass_pending" in mop_due


def test_dispatcher_drops_expired_or_owner_home_requests_before_touching_the_robot() -> None:
    sequence = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean").split(
        "    sequence:", 1
    )[1]

    guard = sequence.index("request_expired | bool(false)")
    stop = sequence.index("- stop:", guard)
    robot_gate = sequence.index("entity_id: vacuum.x40_ultra")
    assert guard < stop < robot_gate

    variables = sequence.split("- if:", 1)[0]
    # Fail closed: an unparseable expiry drops the request, and "away" must be confirmed
    # (unknown/unavailable presence also drops an away-only request).
    assert "limit <= 0 or as_timestamp(now()) > limit" in variables
    assert f"not is_state('{PRESENCE_SENSOR}', 'off')" in variables
    # A bare rendered `false` is a truthy STRING in Jinja `or`; the guard must coerce it.
    assert "(request_expired | bool(false)) or (owner_not_away | bool(false))" in sequence


# --- the vacuum pass is credited reliably (2026-10-26 race) ------------------------


@pytest.mark.parametrize("script_id", ["x40_ultra_main_level_vacuum_only", "x40_ultra_main_level_mop_only"])
def test_completion_waits_for_the_lagging_task_status(script_id: str) -> None:
    sequence = _script_block(VACUUM_PATH, script_id).split("    sequence:", 1)[1]

    # On 2026-10-26 the dock was seen 3 s before task_status flipped to `completed`,
    # so a finished vacuum pass was treated as unfinished and the mop never ran.
    docked = sequence.index("action: script.x40_ultra_wait_until_docked")
    wait = sequence.index("wait_template: \"{{ is_state('sensor.x40_ultra_task_status', 'completed') }}\"")
    check = sequence.index("entity_id: sensor.x40_ultra_task_status", wait)
    assert docked < wait < check
    assert "continue_on_timeout: true" in sequence[wait:check]


@pytest.mark.parametrize("script_id", ["x40_ultra_main_level_vacuum_only", "x40_ultra_main_level_mop_only"])
def test_a_run_docked_early_is_never_credited(script_id: str) -> None:
    sequence = _script_block(VACUUM_PATH, script_id).split("    sequence:", 1)[1]

    # The start time is captured before anything else happens.
    assert sequence.lstrip().split("- variables:", 1)[0].strip().startswith("#")
    assert "run_started_ts: \"{{ as_timestamp(now()) }}\"" in sequence.split("- action:", 1)[0]
    guard = sequence.split("Not docked early by an arrival or dock-all during this run", 1)[1].split("then:", 1)[0]
    assert "state_attr('automation.vacuum_return_home', 'last_triggered')" in guard
    assert "state_attr('script.vacuum_dock_all_robots', 'last_triggered')" in guard
    assert guard.count("< run_started_ts | float(0)") == 2


def test_vacuum_pass_records_when_it_last_completed() -> None:
    text = VACUUM_PATH.read_text(encoding="utf-8")
    helper = _helper_block(text, "x40_ultra_last_vacuumed_at")
    assert "has_date: true" in helper and "has_time: true" in helper

    sequence = _script_block(VACUUM_PATH, "x40_ultra_main_level_vacuum_only").split("    sequence:", 1)[1]
    credited = sequence.split("Not docked early by an arrival or dock-all during this run", 1)[1]
    credited = credited.split("then:", 1)[1].split("else:", 1)[0]
    assert "input_boolean.x40_ultra_vacuum_pass_completed" in credited
    assert "input_datetime.x40_ultra_last_vacuumed_at" in credited


def test_dispatcher_routes_mop_only_requests_to_the_mop_pass() -> None:
    block = _script_block(VACUUM_PATH, "x40_ultra_main_level_policy_clean")
    fields, sequence = block.split("    sequence:", 1)
    assert "mop_only" in fields

    branch = sequence.split("== 'mop_only'", 1)[1].split("- conditions:", 1)[0]
    assert "action: script.x40_ultra_main_level_mop_only" in branch
    # Still behind the same dequeue-time expiry/away guard and the at-rest gate.
    assert sequence.index("request_expired | bool(false)") < sequence.index("== 'mop_only'")
    assert sequence.index("entity_id: vacuum.x40_ultra") < sequence.index("== 'mop_only'")


# --- vacuum_flying_home_recover --------------------------------------------------


def _recover() -> dict:
    return yaml.safe_load(_automation_block(TRIPS_PATH, "vacuum_flying_home_recover"))[0]


def test_recover_fires_when_the_x40_run_ends_or_after_a_restart() -> None:
    triggers = _recover()["trigger"]

    ended = next(t for t in triggers if t.get("id") == "run_ended")
    assert ended["entity_id"] == "script.x40_ultra_main_level_policy_clean"
    assert ended["to"] == "off"
    assert any(t.get("trigger") == "homeassistant" and t.get("event") == "start" for t in triggers)


def test_recover_only_retries_once_for_a_launched_landing_while_away() -> None:
    automation = _recover()
    conditions = yaml.safe_dump(automation["condition"])

    for entity in ("input_boolean.trip", PRESENCE_SENSOR, "input_boolean.guest_mode",
                   "input_boolean.trip_guest_visit_active", "input_select.vacuum_pet_policy"):
        assert entity in conditions
    assert "input_datetime.pre_arrival_clean_done_for" in conditions
    assert "input_datetime.pre_arrival_clean_retry_for" in conditions

    actions = yaml.safe_dump(automation["action"])
    # Busy robot -> hands off; the retry guard is written before anything launches.
    assert actions.index("script.x40_ultra_main_level_policy_clean") < actions.index("plan:")
    assert actions.index("input_datetime.pre_arrival_clean_retry_for") < actions.index("choose:")


def _plan(**values) -> str:
    variables = next(a["variables"] for a in _recover()["action"] if "variables" in a)
    env = jinja2.Environment()
    defaults = {"full_min": 195, "vacuum_only_min": 100, "mop_only_min": 110}
    return env.from_string(variables["plan"]).render(**{**defaults, **values}).strip()


@pytest.mark.parametrize(
    ("vacuum_done", "mop_done", "mop_owed", "remaining", "expected"),
    [
        (False, False, True, 200, "full"),  # HA restart killed the run early
        (False, False, True, 150, "vacuum"),  # not enough for a mop any more
        (False, False, True, 60, "skip"),
        (True, False, True, 120, "mop"),  # 2026-10-26: vacuumed, mop never ran
        (True, False, True, 90, "skip"),
        (True, True, False, 200, "done"),  # finished: never re-run
        (True, False, False, 200, "done"),  # vacuum-only clean, no mop owed
    ],
)
def test_recover_plan_retries_only_what_is_missing_and_still_fits(
    vacuum_done: bool, mop_done: bool, mop_owed: bool, remaining: int, expected: str
) -> None:
    assert _plan(vacuum_done=vacuum_done, mop_done=mop_done, mop_owed=mop_owed,
                 remaining_min=remaining) == expected


def test_recover_launches_match_the_plan_and_expire_at_the_deadline() -> None:
    action = _automation_block(TRIPS_PATH, "vacuum_flying_home_recover").split("    action:", 1)[1]

    full = action.split("plan == 'full'", 1)[1].split("plan == 'vacuum'", 1)[0]
    assert "action: script.vacuum_main_level_full_floor" in full
    assert "force_mop: true" in full

    vacuum = action.split("plan == 'vacuum'", 1)[1].split("plan == 'mop'", 1)[0]
    assert "allow_mop: false" in vacuum

    mop = action.split("plan == 'mop'", 1)[1].split("default:", 1)[0]
    assert "entity_id: script.x40_ultra_main_level_policy_clean" in mop
    assert "kind: mop_only" in mop

    for branch in (full, vacuum, mop):
        assert "require_away: true" in branch
        assert "expires_at: \"{{ finish_iso }}\"" in branch
    assert "action: notify.all" in action.split("default:", 1)[1]


# --- upstairs and den robots are confirmed --------------------------------------


def test_secondary_robots_are_confirmed_retried_once_and_reported() -> None:
    sequence = _script_block(TRIPS_PATH, "pre_arrival_confirm_secondary_robots").split("    sequence:", 1)[1]

    assert sequence.index("input_select.vacuum_pet_policy") < sequence.index("delay:")
    # An arrival during the delay docks these robots (vacuum_return_home); their start
    # scripts don't check presence, so away is re-confirmed before any re-send.
    away = sequence.index(f"entity_id: {PRESENCE_SENSOR}")
    assert sequence.index("delay:") < away < sequence.index("action: script.vacuum_upstairs_full_floor")
    assert away < sequence.index("action: script.vacuum_den_pet_safe_start")
    # One re-send each, through the same guarded start scripts.
    assert sequence.count("action: script.vacuum_upstairs_full_floor") == 1
    assert sequence.count("action: script.vacuum_den_pet_safe_start") == 1
    # Upstairs is confirmed on the trusted Valetudo MQTT status topic, never the flaky
    # upstairs HA vacuum entity; the den on its HA entity.
    assert "vacuum.valetudo_upstairs_vacuum" not in sequence
    assert sequence.count("topic: valetudo/upstairs-vacuum/StatusStateAttribute/status") == 6
    assert "upstairs_ok: \"{{ wait.trigger is not none }}\"" in sequence
    assert "vacuum.valetudo_den" in sequence
    # Says why the den did not start when its doors are the reason.
    assert "binary_sensor.den_doors_contact" in sequence
    assert "action: notify.all" in sequence
