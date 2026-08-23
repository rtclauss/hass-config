from __future__ import annotations

from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"
WATER_SOFTENER_PATH = Path(__file__).resolve().parents[1] / "packages" / "water_softener.yaml"
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / ".storage" / "lovelace.ryan_new_mushroom"


def _derivative_block(path: Path, name: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line == "  - platform: derivative"]
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        block_lines = lines[start:end]
        if any(line.strip() == f"name: {name}" for line in block_lines):
            return "\n".join(block_lines)
    raise AssertionError(f"Could not find derivative sensor block {name!r} in {path}")


def test_house_temp_derivative_sensors_all_set_a_time_window() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    # Without time_window, the derivative platform divides by the raw elapsed
    # time between the last two source states. average_house_temp (a min_max
    # mean over 15 sensors) can emit several states milliseconds apart when
    # multiple sources report in the same poll burst, which turned a tiny
    # real temperature delta into readings like 9917.355 deg F/h (issue #973).
    # Every house-temp derivative sensor must set time_window so it uses the
    # windowed-slope calculation instead.
    names = [
        "Derivative default House Temp Change",
        "Derivative 2.5-5 minutes House Temp Change",
        "Derivative 10-10 minutes House Temp Change",
        "Derivative 30 minutes House Temp Change",
        "Derivative 60 minutes House Temp Change",
    ]
    for name in names:
        block = _derivative_block(CLIMATE_PATH, name)
        assert "time_window:" in block, f"{name} is missing time_window and can spike (#973)"

    assert text.count("source: sensor.average_house_temp") == len(names)


def test_house_temp_derivative_duplicates_were_removed() -> None:
    # "5-5 minutes" and "5-10 minutes" both configured a 5-minute time_window
    # identical to "default" — three sensors computing the same number under
    # different names (#973). Keep exactly one 5-minute sensor.
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    assert "Derivative 5-5 minutes House Temp Change" not in text
    assert "Derivative 5-10 minutes House Temp Change" not in text


def test_house_temp_derivative_window_labels_match_their_time_window() -> None:
    expectations = {
        "Derivative default House Temp Change": '"00:05:00"',
        "Derivative 2.5-5 minutes House Temp Change": '"00:02:30"',
        "Derivative 10-10 minutes House Temp Change": '"00:10:00"',
        "Derivative 30 minutes House Temp Change": '"00:30:00"',
        "Derivative 60 minutes House Temp Change": '"01:00:00"',
    }
    for name, expected_window in expectations.items():
        block = _derivative_block(CLIMATE_PATH, name)
        assert f"time_window: {expected_window}" in block, (
            f"{name} time_window does not match its stated name"
        )


def test_dashboard_does_not_reference_the_removed_duplicate_sensors() -> None:
    # Codex P2 on #973/#975: the Testing dashboard had a history-graph card
    # for each of "5-5 minutes" and "5-10 minutes" (now-deleted duplicates).
    # Left in place they'd render as unavailable-entity cards after reload.
    text = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "sensor.derivative_5_5_minutes_house_temp_change" not in text
    assert "sensor.derivative_5_10_minutes_house_temp_change" not in text
    # The surviving sensors' cards should still be there.
    assert "sensor.derivative_default_house_temp_change" in text
    assert "sensor.derivative_10_10_minutes_house_temp_change" in text


def test_water_softener_derivative_sensors_all_set_a_time_window() -> None:
    text = WATER_SOFTENER_PATH.read_text(encoding="utf-8")

    names = [
        "Water Softener Level (dt=24hrs)",
        "Water Softener Level (dt=48hrs)",
        "Water Softener Level (dt=72hrs)",
        "Water Softener Level (dt=7d)",
    ]
    for name in names:
        block = _derivative_block(WATER_SOFTENER_PATH, name)
        assert "time_window:" in block, f"{name} is missing time_window and can spike"

    assert text.count("source: sensor.water_softener_salt_level") == len(names)
