"""The flying-home clean must FINISH before the plane lands.

On 2026-10-09 the clean was started at takeoff, but a full vacuum+mop cycle (182-191 min)
is longer than the 150 min flight, and two more requests stacked behind it in the single
X40 queue and ran after the owner got home. These tests pin the fix: the clean is anchored
to the flight's ARRIVAL, flying-home days don't stack other launches, and queued requests
are re-validated when they are dequeued.
"""

from __future__ import annotations

from pathlib import Path


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

    # 2026-10-06..09 X40 history: vacuum 81-87 min, mop 97-104 min, full cycle 182-191.
    assert "initial: 210" in helper
    assert "min: 120" in helper
    assert "max: 360" in helper


def test_done_for_helper_is_a_date_time_run_once_guard() -> None:
    helper = _helper_block(TRIPS_PATH.read_text(encoding="utf-8"), "pre_arrival_clean_done_for")

    assert "has_date: true" in helper
    assert "has_time: true" in helper


def test_arrival_sensor_reads_both_flight_sensors_end_time() -> None:
    text = TRIPS_PATH.read_text(encoding="utf-8")
    block = text.split("name: Next Flight Home Arrival", 1)[1].split("name: Pre-Arrival Clean Start", 1)[0]

    assert "device_class: timestamp" in block
    assert "binary_sensor.flight_to_msp_today" in block
    assert "binary_sensor.flight_to_rst_today" in block
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
        ("binary_sensor.bayesian_zeke_home", "off"),
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

    # Enough time for a whole cycle -> full cycle with a forced mop. The bar is the
    # worst observed cycle (195 min), or the lead minus 5 min of trigger jitter if the
    # lead was set lower, so the scheduled start is always "full" and a catch-up a few
    # minutes late (e.g. an HA restart) still gets its mop.
    assert 'full_min: "{{ [lead_min - 5, 195] | min }}"' in action
    assert "remaining_min >= full_min" in action
    # Otherwise vacuum-only while a ~85 min vacuum pass still fits, otherwise skip.
    assert "vacuum_only_min: 100" in action
    assert "remaining_min >= vacuum_only_min" in action

    full = action.split("plan == 'full'", 1)[1].split("plan == 'vacuum'", 1)[0]
    assert "force_mop: true" in full
    assert "allow_mop" not in full
    assert "expires_at: \"{{ arrival_iso }}\"" in full

    vacuum = action.split("plan == 'vacuum'", 1)[1].split("default:", 1)[0]
    assert "force_mop: false" in vacuum
    assert "allow_mop: false" in vacuum
    assert "expires_at: \"{{ arrival_iso }}\"" in vacuum

    skipped = action.split("default:", 1)[1]
    assert "action: notify.all" in skipped
    assert "script.trip_vacuum_main_and_upstairs_levels" not in skipped


def test_flying_home_requests_are_dropped_if_owner_is_home_or_after_landing() -> None:
    block = _automation_block(TRIPS_PATH, "vacuum_flying_home")

    assert block.count("require_away: true") == 2  # full + vacuum-only launches
    assert block.count("expires_at: \"{{ arrival_iso }}\"") == 2


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
    assert "not is_state('binary_sensor.bayesian_zeke_home', 'off')" in variables
    # A bare rendered `false` is a truthy STRING in Jinja `or`; the guard must coerce it.
    assert "(request_expired | bool(false)) or (owner_not_away | bool(false))" in sequence
