from __future__ import annotations

from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / ".storage" / "lovelace.ryan_new_mushroom"


def test_dead_change_rate_statistics_chain_is_removed() -> None:
    # sensor.house_temperature_stats_* / rate_of_house_temp_change_* /
    # min_rate_of_house_temp_change_* all depended on a `change_rate`
    # attribute that this HA version's `statistics` platform never exposes
    # for state_characteristic: mean (confirmed live: the entity's only
    # extra attributes are buffer_usage_ratio, age_coverage_ratio,
    # source_value_valid). state_attr(..., 'change_rate') was always None,
    # so ecobee_modeled_rate_deg_per_min's "recent_rate" blend was silently
    # dead weight, always 0, for as long as this config existed (issue #977).
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    for stale_sensor in (
        "house_temperature_stats_5m",
        "house_temperature_stats_10m",
        "house_temperature_stats_30m",
        "house_temperature_stats_1h",
        "rate_of_house_temp_change_5m",
        "rate_of_house_temp_change_10m",
        "rate_of_house_temp_change_30m",
        "rate_of_house_temp_change_1h",
        "min_rate_of_house_temp_change_10m",
        "min_rate_of_house_temp_change_1h",
        "min_rate_of_house_temp_change_30m",
    ):
        assert f"name: {stale_sensor}\n" not in text, f"{stale_sensor!r} should have been removed (#977)"
        assert f"unique_id: {stale_sensor}\n" not in text, f"{stale_sensor!r} should have been removed (#977)"


def test_ecobee_modeled_rate_uses_the_audited_derivative_sensor() -> None:
    # Recent-rate feedback now comes from sensor.derivative_10_10_minutes_
    # house_temp_change (deg F/hour, the sensor recommended for day-to-day
    # use in #973), converted to deg F/min to match hist_rate's units.
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    marker = "unique_id: ecobee_modeled_rate_deg_per_min"
    start = text.index(marker)
    end = text.index("name: ecobee_modeled_rate_deg_per_min", start)
    block = text[start:end]

    assert "has_value('sensor.derivative_10_10_minutes_house_temp_change')" in block
    assert (
        "states('sensor.derivative_10_10_minutes_house_temp_change') | float(default=0)) / 60"
        in block
    )


def test_ecobee_modeled_rate_clamps_recent_rate_to_a_sane_bound() -> None:
    # Codex P2 on #973/#975: time_window bounds max sample age, not a
    # minimum, so a burst of samples milliseconds apart right after an HA
    # restart/reload can still dominate the windowed derivative before real
    # history accumulates. recent_rate must be clamped so a spike can only
    # ever nudge the blend by a bounded amount, not dominate it.
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    marker = "unique_id: ecobee_modeled_rate_deg_per_min"
    start = text.index(marker)
    end = text.index("name: ecobee_modeled_rate_deg_per_min", start)
    block = text[start:end]

    assert "recent_rate_sanity_bound = 0.05" in block
    assert (
        "recent_rate = [[raw_recent_rate, -recent_rate_sanity_bound] | max, "
        "recent_rate_sanity_bound] | min"
        in block
    )


def test_dashboard_does_not_reference_the_removed_dead_rate_sensors() -> None:
    # Codex P2 on #977: the Testing dashboard had a "Rate of Temp Change"
    # history-graph card pointed at the three now-deleted dead sensors.
    # Left in place it would render as an unavailable-entity graph after
    # the next config reload.
    text = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "sensor.rate_of_house_temp_change_5m" not in text
    assert "sensor.rate_of_house_temp_change_30m" not in text
    assert "sensor.rate_of_house_temp_change_1h" not in text
