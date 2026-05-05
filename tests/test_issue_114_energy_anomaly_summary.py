from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"


def _automation_block(automation_id: str) -> str:
    lines = UTILITIES_PATH.read_text(encoding="utf-8").splitlines()
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
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_energy_anomaly_uses_native_numeric_state_and_sleep_or_empty_modes() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")
    block = _automation_block("notify_energy_anomaly_high_empty_house_usage")

    assert "energy_anomaly_hourly_kwh_threshold:" in text
    assert "name: hourly_home_electricity_energy" in text
    assert "sensor.hourly_electricity_non_summer" in text
    assert "sensor.hourly_electricity_summer" in text
    assert "trigger: numeric_state" in block
    assert "entity_id: sensor.hourly_home_electricity_energy" in block
    assert "above: input_number.energy_anomaly_hourly_kwh_threshold" in block
    assert "condition: state" in block
    assert "entity_id: input_select.house_mode" in block
    for mode in ("away", "night", "in_bed", "asleep"):
        assert f"          - {mode}" in block
    assert "notification_id: energy-anomaly-high-load" in block
    assert "tag: energy-anomaly-high-load" in block
    assert "notify.all" in block


def test_weekly_energy_summary_uses_tariffed_last_period_costs() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")
    tariff_block = _automation_block("switch_electrical_tariff")
    block = _automation_block("notify_weekly_energy_cost_summary")

    assert "weekly_electricity:" in text
    assert "entity_id: select.weekly_electricity" in tariff_block
    assert "name: daily_home_electricity_cost" in text
    assert "name: weekly_home_electricity_cost" in text
    assert "name: monthly_home_electricity_cost" in text
    assert "sensor.weekly_electricity_non_summer" in block
    assert "sensor.weekly_electricity_summer" in block
    assert "sensor.weekly_ev_charging_off_peak" in block
    assert "sensor.weekly_ev_charging_mid_peak" in block
    assert "sensor.weekly_ev_charging_on_peak" in block
    assert "state_attr('sensor.weekly_electricity_non_summer', 'last_period')" in block
    assert "0.1397" in block
    assert "0.1258" in block
    assert "0.0755" in block
    assert "0.4420" in block
    assert "weekday:" in block
    assert "          - mon" in block
    assert "tag: weekly-energy-cost-summary" in block
