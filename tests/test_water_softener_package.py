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


def _robust_forecast_rate(
    rates: list[float | None],
    *,
    minimum_rate: float = 0.5,
) -> float | None:
    valid_rates = sorted(rate for rate in rates if rate is not None and rate > minimum_rate)
    if len(valid_rates) < 2:
        return None
    middle = len(valid_rates) // 2
    if len(valid_rates) % 2:
        return valid_rates[middle]
    return (valid_rates[middle - 1] + valid_rates[middle]) / 2


def test_water_softener_forecast_rate_uses_guarded_multi_window_median() -> None:
    block = _template_sensor_block("Water Softener Forecast Rate")

    assert "unique_id: water_softener_forecast_rate" in block
    assert "unit_of_measurement: mm/d" in block
    assert "float(default=none)" in block
    assert "sensor.water_softener_level_dt_24hrs" in block
    assert "sensor.water_softener_level_dt_48hrs" in block
    assert "sensor.water_softener_level_dt_72hrs" in block
    assert "sensor.water_softener_level_dt_7d" in block
    assert "select('gt', minimum_rate)" in block
    assert "valid_rates | count >= 2" in block
    assert "rates | count % 2" in block


def test_water_softener_forecast_rate_rejects_noise_and_outlier_windows() -> None:
    assert _robust_forecast_rate([0.1, 4.0, 4.5, 40.0]) == 4.5
    assert _robust_forecast_rate([0.1, None, 0.5, -10.0]) is None
    assert _robust_forecast_rate([None, 3.0, 5.0, None]) == 4.0


def test_water_softener_forecast_uses_statistics_smoothed_rate() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")
    block = _template_sensor_block("Water Softener Days Until Low Salt")

    assert "platform: statistics" in text
    assert "entity_id: sensor.water_softener_forecast_rate" in text
    assert "state_characteristic: median" in text
    assert "hours: 24" in text
    assert "unique_id: water_softener_days_until_low_salt" in block
    assert "unit_of_measurement: d" in block
    assert "sensor.water_softener_forecast_rate_median_24h" in block
    assert "level >= threshold" in block
    assert "rate is none or rate <= 0" in block
    assert "((threshold - level) / rate) | round(1)" in block


def test_water_softener_forecast_excludes_recent_refill_from_7d_rate() -> None:
    block = _template_sensor_block("Water Softener Forecast Rate")

    assert "input_datetime.water_softener_last_refill_at" in block
    assert "as_timestamp(now()) - last_refill_at >= 7 * 24 * 60 * 60" in block
    assert "if include_7d else none" in block


def test_water_softener_forecast_low_date_projects_days_remaining() -> None:
    block = _template_sensor_block("Water Softener Forecast Low Salt At")
    now = datetime(2026, 6, 2, 12, tzinfo=UTC)

    assert "device_class: timestamp" in block
    assert "sensor.water_softener_days_until_low_salt" in block
    assert "(now() + timedelta(days=days)).isoformat()" in block
    assert now + timedelta(days=4.5) == datetime(2026, 6, 7, 0, tzinfo=UTC)


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

    assert "trigger: state" in block
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
