from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATER_SOFTENER_PATH = ROOT / "packages" / "water_softener.yaml"
OTHER_TILE_PATH = ROOT / "lovelace" / "tiles" / "tiles_other.yaml"


def _automation_block(automation_id: str) -> str:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def _template_sensor_block(sensor_name: str) -> str:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^      - name: {re.escape(sensor_name)}\n(.*?)(?=^      - name: |^########################)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find template sensor block {sensor_name!r}")
    return match.group(0)


def _statistics_block(name: str) -> str:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - platform: statistics\n(?:(?!^  - ).*\n)*?    name: {re.escape(name)}\n(?:(?!^  - |^#).*\n)*",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find statistics sensor block {name!r}")
    return match.group(0)


def _live_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def _rolling_24h_change_median(samples: list[tuple[float, float]], at: float, median_days: float) -> float:
    """Pure-Python mirror of the two statistics sensors: a `change` over 24h on
    salt_level, then a `median` of that over `median_days` (sample-weighted)."""
    def change_24h(t: float) -> float | None:
        window = [v for (ts, v) in samples if t - 86400 <= ts <= t]
        return window[-1] - window[0] if len(window) > 1 else None

    changes = [c for (ts, _) in samples
               if at - median_days * 86400 <= ts <= at and (c := change_24h(ts)) is not None]
    changes.sort()
    mid = len(changes) // 2
    return changes[mid] if len(changes) % 2 else (changes[mid - 1] + changes[mid]) / 2


def test_water_softener_rate_is_restart_safe_median_of_24h_changes() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")

    # derivative sensors keep their window only in memory and divide by the
    # full window, so every HA restart under-reported the rate for up to the
    # window length (replayed against the recorded 2026-09/10 data). statistics
    # reloads its buffer from the recorder at startup.
    assert "platform: derivative" not in text
    assert "water_softener_level_dt_" not in text
    assert "water_softener_forecast_rate_median_24h" not in text

    change = _statistics_block("Water Softener Level Change 24h")
    assert "unique_id: water_softener_level_change_24h" in change
    assert "entity_id: sensor.water_softener_salt_level" in change
    assert "state_characteristic: change" in change
    assert "hours: 24" in change
    assert "sampling_size:" in change

    median = _statistics_block("Water Softener Level Change 24h Median 14d")
    assert "unique_id: water_softener_level_change_24h_median_14d" in median
    assert "entity_id: sensor.water_softener_level_change_24h" in median
    assert "state_characteristic: median" in median
    assert "days: 14" in median
    assert "sampling_size:" in median

    rate = _template_sensor_block("Water Softener Forecast Rate")
    assert "unique_id: water_softener_forecast_rate" in rate
    assert "unit_of_measurement: mm/d" in rate
    assert "sensor.water_softener_level_change_24h_median_14d" in rate
    assert "rate is not none and rate > minimum_rate" in rate
    # The refill no longer needs special-casing: the median ignores it.
    assert "last_refill_at" not in rate


def test_median_of_24h_changes_survives_refill_and_slump_where_window_slope_fails() -> None:
    # Synthetic version of the recorded history: 0.46 mm/day of real depletion,
    # a +-0.12 mm daily wobble, a refill (-277 mm) and a one-off +20 mm slump,
    # sampled every 30 minutes.
    import math

    drift_per_day = 0.46
    refill_day, slump_day = 2.0, 6.0
    samples: list[tuple[float, float]] = []
    for i in range(int(20 * 48)):
        day = i / 48
        level = 451.0 + drift_per_day * day + 0.12 * math.sin(2 * math.pi * day)
        if day >= refill_day:
            level -= 277.0
        if day >= slump_day:
            level += 20.0
        samples.append((day * 86400, level))

    at = 12 * 86400.0  # 10 days after the refill, 6 days after the slump
    median_rate = _rolling_24h_change_median(samples, at, 14)
    in_window = [v for (ts, v) in samples if at - 14 * 86400 <= ts <= at]
    window_slope = (in_window[-1] - in_window[0]) / 14

    assert abs(median_rate - drift_per_day) < 0.05
    assert abs(window_slope - drift_per_day) > 1.0  # a single 14d slope is poisoned


def test_water_softener_forecast_uses_statistics_smoothed_rate() -> None:
    block = _template_sensor_block("Water Softener Days Until Low Salt")

    assert "unique_id: water_softener_days_until_low_salt" in block
    assert "unit_of_measurement: d" in block
    assert "states('sensor.water_softener_forecast_rate')" in block
    assert "level >= threshold" in block
    assert "rate is none or rate <= 0" in block
    assert "((threshold - level) / rate) | round(1)" in block


def test_water_softener_forecast_low_date_projects_days_remaining() -> None:
    block = _template_sensor_block("Water Softener Forecast Low Salt At")
    computed_at = datetime(2026, 6, 2, 12, tzinfo=UTC)

    assert "device_class: timestamp" in block
    assert "sensor.water_softener_days_until_low_salt" in block
    # Anchored to when the forecast was computed: a now()-based template
    # re-renders every minute and drifts the date forward between updates.
    assert "now()" not in "\n".join(_live_lines(block))
    assert "states.sensor.water_softener_days_until_low_salt.last_changed" in block
    assert "(computed_at + timedelta(days=days)).isoformat()" in block
    assert computed_at + timedelta(days=4.5) == datetime(2026, 6, 7, 0, tzinfo=UTC)


def test_salt_level_filter_is_cadence_independent() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")
    sensor_section = text.split("\nsensor:\n", 1)[1].split("\n########################", 1)[0]
    live = _live_lines(sensor_section)

    # HA's lowpass is per state update (no time term): its effective time
    # constant scales with the firmware publish interval (~1.7h at ~50s,
    # ~10h at 5 minutes). Only the time-weighted 6h average remains.
    assert "- filter: lowpass" not in live
    assert "- filter: time_simple_moving_average" in live
    assert 'window_size: "6:00"' in live


def test_salt_notifications_link_to_existing_cleaning_view() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")

    # The dashboard view moved to `cleaning-v2`; `cleaning` no longer exists.
    assert 'url: "/ryan-new-mushroom/cleaning"' not in text
    assert text.count('url: "/ryan-new-mushroom/cleaning-v2"') == 2


def test_water_softener_forecast_reminder_is_one_shot_before_critical() -> None:
    block = _automation_block("water_softener_forecast_refill_reminder")

    assert "trigger: state" in block
    assert "entity_id: sensor.water_softener_days_until_low_salt" in block
    assert "below: input_number.water_softener_refill_reminder_days" in block
    assert "trigger: time_pattern" in block
    assert "event: start" in block
    assert "condition: state" in block
    assert "entity_id: input_boolean.water_softener_refill_reminder_sent" in block
    assert "state: \"off\"" in block
    assert "below: input_number.water_softener_low_salt_threshold_mm" in block
    assert "input_datetime.water_softener_forecast_window_entered_at" in block
    assert "as_timestamp(now()) - entered_at >= 6 * 60 * 60" in block
    assert "action: input_boolean.turn_on" in block
    assert "tag: water-softener-forecast-low" in block
    assert "states('input_number.bags_of_salt_at_home') | int(default=0)" in block


def test_water_softener_forecast_monitor_persists_entry_time() -> None:
    block = _automation_block("water_softener_forecast_refill_reminder")

    assert "entity_id: sensor.water_softener_days_until_low_salt" in block
    assert "event: start" in block
    assert "below: input_number.water_softener_refill_reminder_days" in block
    assert "input_datetime.water_softener_forecast_window_entered_at" in block
    assert "              - if:" in block
    assert 'timestamp: "{{ as_timestamp(now()) }}"' in block
    assert "days is not none and reminder_days is not none" in block
    assert "timestamp: 0" in block


def test_water_softener_refill_resets_next_reminder_cycle() -> None:
    block = _automation_block("water_softener_refill_reminder_reset")

    # Threshold crossings, not every salt_level update (47k automation state
    # rows in ~40 days when it fired on each update).
    assert "trigger: state" not in block
    assert block.count("trigger: numeric_state") == 2
    assert "above: input_number.water_softener_refill_reset_threshold_mm" in block
    assert "entity_id: sensor.water_softener_salt_level" in block
    assert "trigger: time_pattern" in block
    assert "event: start" in block
    assert "below: input_number.water_softener_refill_reset_threshold_mm" in block
    assert "input_datetime.water_softener_refill_window_entered_at" in block
    assert "as_timestamp(now()) - entered_at >= 6 * 60 * 60" in block
    assert "state: \"on\"" in block
    assert "action: input_boolean.turn_off" in block
    assert "input_datetime.water_softener_last_refill_at" in block


def test_water_softener_refill_monitor_persists_entry_time() -> None:
    block = _automation_block("water_softener_refill_reminder_reset")

    assert "entity_id: sensor.water_softener_salt_level" in block
    assert "event: start" in block
    assert "below: input_number.water_softener_refill_reset_threshold_mm" in block
    assert "input_datetime.water_softener_refill_window_entered_at" in block
    assert "              - if:" in block
    assert 'timestamp: "{{ as_timestamp(now()) }}"' in block
    assert "level is not none and reset_threshold is not none" in block
    assert "timestamp: 0" in block


def test_water_softener_window_timestamps_restore_across_restarts() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")
    input_datetimes = text.split("input_datetime:", maxsplit=1)[1].split(
        "########################\n# Input Numbers", maxsplit=1
    )[0]

    assert "water_softener_forecast_window_entered_at:" in input_datetimes
    assert "water_softener_refill_window_entered_at:" in input_datetimes
    assert "water_softener_last_refill_at:" in input_datetimes
    assert input_datetimes.count("has_date: true") == 3
    assert input_datetimes.count("has_time: true") == 3
    assert "initial:" not in input_datetimes


def test_water_softener_forecast_status_is_visible_on_home_dashboard_tile() -> None:
    text = OTHER_TILE_PATH.read_text(encoding="utf-8")

    assert "title: Water Softener" in text
    assert "entity: sensor.water_softener_forecast_status" in text
    assert "entity: sensor.water_softener_days_until_low_salt" in text
    assert "entity: sensor.water_softener_forecast_low_salt_at" in text
    assert "entity: sensor.water_softener_salt_level" in text
    assert "entity: input_number.bags_of_salt_at_home" in text


def test_low_salt_threshold_template_fallbacks_track_calibrated_value() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")

    # Regression guard: the low-salt threshold input_number is calibrated
    # as 75% depleted between the two real measured baselines (confirmed-
    # just-refilled ~172mm, confirmed-empty ~451mm): 172 + 0.75*(451-172)
    # ~= 381, rounded to the step:10 grid -> 380mm. This replaced an
    # earlier 440mm calibration (~10mm short of bare water) that made
    # "low salt" mean "almost completely out" with too little real lead
    # time. The three template sensors that read the threshold also carry
    # a float(default=...) fallback for the brief window where the
    # input_number is transiently unknown/unavailable (e.g. HA startup
    # before helpers load) -- a stale fallback there would silently mask
    # a real low-salt state during that window (caught in review). All
    # three fallbacks must track the same calibrated value, not an old
    # or ad-hoc one.
    assert "initial: 380" in text
    fallback_count = text.count(
        "states('input_number.water_softener_low_salt_threshold_mm') "
        "| float(default=380)"
    )
    assert fallback_count == 3
    assert "float(default=500)" not in text
    assert "float(default=440)" not in text


def test_refill_reset_threshold_calibrated_between_empty_and_full_baselines() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")

    # Regression guard: refill_reset_threshold_mm is calibrated against a
    # real 2026-09-16 refill (confirmed-empty ~451mm -> confirmed-just-
    # refilled ~170-174mm). 300mm must stay strictly between the low-salt
    # threshold (380mm, the 75%-depleted side) and today's observed
    # full-tank reading, so it can never misfire on normal depletion near
    # empty nor fail to detect a lighter future refill.
    assert "initial: 300" in text

    low_salt_threshold = 380
    refill_reset_threshold = 300
    observed_full_reading = 172

    assert observed_full_reading < refill_reset_threshold < low_salt_threshold


def test_minimum_depletion_rate_and_forecast_fallbacks_stay_in_sync() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")

    # Regression guard: 0.2 mm/day admits genuinely slow-but-real depletion
    # (the recorded steady rate is ~0.4-0.5 mm/day) while staying above the
    # pure post-refill settling noise observed (-0.05 to -0.32 mm/day). The
    # 0.448 mm/day 7-day reading that first prompted lowering it from 0.5 was
    # later found to be depressed by derivative restart amnesia; the floor
    # still holds on its own merits.
    assert "initial: 0.2" in text

    # The forecast_rate template's float(default=...) fallback (for the
    # brief window where the input_number is transiently unknown/
    # unavailable) must track the same calibrated value -- a stale
    # fallback here would silently exclude real depletion during that
    # window, the same class of bug caught in review for the low-salt
    # threshold's fallbacks.
    fallback_count = text.count(
        "states('input_number.water_softener_minimum_depletion_rate_mm_per_day') "
        "| float(default=0.2)"
    )
    assert fallback_count == 1
    assert "float(default=0.5)" not in text
