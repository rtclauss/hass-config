from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "sleep_quality.yaml"
DASHBOARD_PATH = ROOT / "lovelace" / "tiles" / "tiles_master_bedroom.yaml"


def _automation_block(automation_id: str) -> str:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def _script_block(script_id: str) -> str:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  {re.escape(script_id)}:\n(.*?)(?=^automation:)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find script block {script_id!r}")
    return match.group(0)


def test_sleep_session_uses_restorable_native_helpers() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")
    input_datetimes = text.split("input_datetime:", maxsplit=1)[1].split(
        "input_number:", maxsplit=1
    )[0]
    score_helper = text.split("  sleep_quality_score:", maxsplit=1)[1].split(
        "counter:", maxsplit=1
    )[0]

    for helper_id in (
        "sleep_session_bed_in",
        "sleep_session_cpap_on",
        "sleep_session_cpap_off",
        "sleep_session_bed_out",
    ):
        assert f"  {helper_id}:" in input_datetimes
    assert input_datetimes.count("has_date: true") == 4
    assert input_datetimes.count("has_time: true") == 4
    assert "restore: true" in text.split("counter:", maxsplit=1)[1].split(
        "script:", maxsplit=1
    )[0]
    assert "initial:" not in score_helper
    assert "\ntemplate:" not in text


def test_cpap_session_records_timestamps_and_counts_only_guarded_bed_transitions() -> None:
    prepare = _automation_block("sleep_quality_prepare_session")
    active = _automation_block("sleep_quality_track_active_session")

    assert "id: bed_entry" in prepare
    assert "id: cpap_start" in prepare
    assert "entity_id: sensor.owner_suite_cpap_plug_power" in prepare
    assert "above: 1.3" in prepare
    assert "seconds: 10" in prepare
    assert "entity_id: input_datetime.sleep_session_cpap_on" in prepare

    assert "binary_sensor.bed_presence_2d0670_bed_occupied_left" in active
    assert "binary_sensor.bed_presence_2d0670_bed_occupied_right" in active
    assert active.count("id: bed_transition") == 3
    assert 'from: "on"' in active
    assert 'to: "off"' in active
    assert 'from: "off"' in active
    assert 'to: "on"' in active
    assert "condition: numeric_state" in active
    assert "action: counter.increment" in active
    assert "entity_id: counter.sleep_restlessness_events" in active

    assert "id: cpap_stop" in active
    assert "below: 1.3" in active
    assert active.count("minutes: 5") == 2
    assert "entity_id: input_datetime.sleep_session_cpap_off" in active
    assert "id: bed_exit" in active
    assert active.count("below: 1.3") == 2


def test_continuity_score_is_bounded_and_does_not_change_governed_routines() -> None:
    block = _script_block("finalize_sleep_quality_session")
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    assert "cpap_points = [60" in block
    assert "bed_points = [40" in block
    assert "transition_penalty = [20" in block
    assert "[100, [0, cpap_points + bed_points - transition_penalty] | max] | min" in block
    assert "input_number.sleep_quality_score" in block
    assert "script.wake_up_script" not in text
    assert "script.goodnight_integrity" not in text
    assert "wakeup_alarm_firing" not in text


def test_owner_suite_dashboard_shows_recent_sleep_history() -> None:
    dashboard = DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "title: Sleep continuity (heuristic)" in dashboard
    assert "hours_to_show: 336" in dashboard
    assert "entity: input_number.sleep_quality_score" in dashboard
    assert "entity: counter.sleep_restlessness_events" in dashboard
    assert "entity: input_number.sleep_session_bed_minutes" in dashboard
    assert "entity: input_number.sleep_session_cpap_minutes" in dashboard
