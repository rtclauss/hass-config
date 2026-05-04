from __future__ import annotations

import re
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


def test_water_softener_forecast_sensor_uses_guarded_derivative_trend() -> None:
    block = _template_sensor_block("Water Softener Days Until Low Salt")

    assert "unique_id: water_softener_days_until_low_salt" in block
    assert "unit_of_measurement: d" in block
    assert "float(default=none)" in block
    assert "sensor.water_softener_level_dt_7d" in block
    assert "sensor.water_softener_level_dt_72hrs" in block
    assert "rate_7d if rate_7d is not none and rate_7d > 0 else rate_72h" in block
    assert "level >= threshold" in block
    assert "rate is none or rate <= 0" in block
    assert "((threshold - level) / rate) | round(1)" in block


def test_water_softener_forecast_reminder_is_one_shot_before_critical() -> None:
    block = _automation_block("water_softener_forecast_refill_reminder")

    assert "trigger: numeric_state" in block
    assert "entity_id: sensor.water_softener_days_until_low_salt" in block
    assert "below: input_number.water_softener_refill_reminder_days" in block
    assert "for:\n          hours: 6" in block
    assert "condition: state" in block
    assert "entity_id: input_boolean.water_softener_refill_reminder_sent" in block
    assert "state: \"off\"" in block
    assert "below: input_number.water_softener_low_salt_threshold_mm" in block
    assert "action: input_boolean.turn_on" in block
    assert "tag: water-softener-forecast-low" in block
    assert "states('input_number.bags_of_salt_at_home') | int(default=0)" in block


def test_water_softener_refill_resets_next_reminder_cycle() -> None:
    block = _automation_block("water_softener_refill_reminder_reset")

    assert "trigger: numeric_state" in block
    assert "entity_id: sensor.water_softener_salt_level" in block
    assert "below: input_number.water_softener_refill_reset_threshold_mm" in block
    assert "for:\n          hours: 6" in block
    assert "state: \"on\"" in block
    assert "action: input_boolean.turn_off" in block


def test_water_softener_forecast_status_is_visible_on_home_dashboard_tile() -> None:
    text = OTHER_TILE_PATH.read_text(encoding="utf-8")

    assert "title: Water Softener" in text
    assert "entity: sensor.water_softener_forecast_status" in text
    assert "entity: sensor.water_softener_days_until_low_salt" in text
    assert "entity: sensor.water_softener_salt_level" in text
    assert "entity: input_number.bags_of_salt_at_home" in text
