from __future__ import annotations

from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"


def _trend_sensor_gradient(text: str, name: str, sample_duration: int = 10800) -> float:
    # Anchor on the exact trend-sensor block shape so this can't accidentally
    # match the unrelated `customize:` entry that shares the same entity name.
    marker = (
        f"      {name}:\n"
        "        entity_id: sensor.average_house_pressure\n"
        f"        sample_duration: {sample_duration}\n"
        "        max_samples: 500\n"
        "        min_gradient: "
    )
    start = text.index(marker) + len(marker)
    end = text.index("\n", start)
    return float(text[start:end])


def test_pressure_trend_thresholds_are_reachable_in_inhg() -> None:
    # sensor.average_house_pressure reports inHg (confirmed live: device_class
    # atmospheric_pressure, unit inHg), but min_gradient — which the trend
    # platform reads as <source unit>/second — was calibrated for hPa/s.
    # 1 inHg = 33.8639 hPa, so the old values implied 0.54-1.98 inHg/hr
    # (18-67 hPa/hr) for the falling/quickly/v_rapidly tiers: rates never
    # once observed in 72h of real history (largest ~1hr rate was
    # -0.043 inHg/hr, ~1.45 hPa/hr). Those three tiers could never fire
    # (issue #974). Values must now be small enough to be reachable by real
    # weather-driven pressure changes.
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    thresholds = {
        "pressure_falling_v_rapidly": -0.0000162,
        "pressure_rising_v_rapidly": 0.0000162,
        "pressure_falling_quickly": -0.0000097,
        "pressure_rising_quickly": 0.0000097,
        "pressure_falling": -0.0000044,
        "pressure_rising": 0.0000044,
        "pressure_falling_slowly": -0.00000027,
        "pressure_rising_slowly": 0.00000027,
    }
    for name, expected in thresholds.items():
        actual = _trend_sensor_gradient(text, name)
        assert actual == expected, f"{name} min_gradient={actual}, expected {expected}"

    # The old hPa-calibrated magnitudes must be gone.
    for stale in ("-0.00055", "-0.00033", "-0.00015", "-0.000009\n"):
        assert stale not in text


def test_pressure_trend_sensors_set_max_samples() -> None:
    # Codex P1: the trend platform's config schema defaults max_samples to 2
    # regardless of sample_duration, so without an explicit max_samples every
    # one of these sensors — including the 3-hour ones — would compute its
    # gradient from whichever 2 samples happen to be in the buffer, which can
    # still be milliseconds apart during a burst (the same instability
    # behind the temperature derivative spike in #973).
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    assert text.count("sample_duration: 10800\n        max_samples: 500\n") == 8
    assert text.count("sample_duration: 1800\n        max_samples: 500\n") == 2


def test_pressure_trend_severity_ordering_is_preserved() -> None:
    # Whatever the exact values, v_rapidly must stay the largest-magnitude
    # threshold and slowly the smallest, in both directions, so the four
    # tiers still escalate in the intended order.
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    v_rapidly = abs(_trend_sensor_gradient(text, "pressure_falling_v_rapidly"))
    quickly = abs(_trend_sensor_gradient(text, "pressure_falling_quickly"))
    falling = abs(_trend_sensor_gradient(text, "pressure_falling"))
    slowly = abs(_trend_sensor_gradient(text, "pressure_falling_slowly"))

    assert v_rapidly > quickly > falling > slowly > 0


def test_pressure_fast_short_window_sensor_is_above_the_measured_noise_floor() -> None:
    # 30 days of live history showed indoor 30-minute rates spiking to
    # ~6.6 hPa/hr from ordinary multi-sensor-mean noise alone (a milder
    # version of the burst effect behind #973). The fast tier must sit
    # meaningfully above that so it doesn't flap on routine noise, while
    # still being far below the frontal-scale 3-hour thresholds — a short
    # window needs a much higher instantaneous rate to represent a real,
    # fast-developing event.
    text = CLIMATE_PATH.read_text(encoding="utf-8")

    falling_fast = _trend_sensor_gradient(text, "pressure_falling_fast", sample_duration=1800)
    rising_fast = _trend_sensor_gradient(text, "pressure_rising_fast", sample_duration=1800)
    assert falling_fast == -0.000082
    assert rising_fast == 0.000082

    measured_30min_noise_ceiling_inhg_per_s = (6.6 / 33.8639) / 3600  # ~6.6 hPa/hr
    assert abs(falling_fast) > measured_30min_noise_ceiling_inhg_per_s * 1.25

    v_rapidly = abs(_trend_sensor_gradient(text, "pressure_falling_v_rapidly"))
    assert abs(falling_fast) > v_rapidly, (
        "a 30-minute window needs a higher instantaneous rate than the "
        "3-hour v_rapidly tier to represent an equally significant event"
    )


def test_pressure_binary_sensors_have_no_invalid_device_class() -> None:
    # "pressure" is not a valid binary_sensor device_class (only sensor
    # entities have pressure/atmospheric_pressure device classes) — see
    # https://www.home-assistant.io/integrations/binary_sensor/. Reconciled
    # away in #974; these are trend/direction flags and don't need one.
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    names = [
        "pressure_falling",
        "pressure_falling_quickly",
        "pressure_falling_slowly",
        "pressure_falling_v_rapidly",
        "pressure_falling_fast",
        "pressure_rising",
        "pressure_rising_quickly",
        "pressure_rising_slowly",
        "pressure_rising_v_rapidly",
        "pressure_rising_fast",
    ]
    for name in names:
        marker = f"binary_sensor.{name}:\n      <<: *customize\n      friendly_name: "
        start = text.index(marker)
        end = text.index("\n\n", start)
        block = text[start:end]
        assert "device_class:" not in block, f"binary_sensor.{name} should not set device_class"


def test_average_house_pressure_device_class_matches_its_sources() -> None:
    # The 9 _tph_pressure sensors it averages all report device_class:
    # atmospheric_pressure; the aggregate had drifted to device_class:
    # pressure instead (#974).
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    marker = (
        "sensor.average_house_pressure:\n"
        "      <<: *customize\n"
        '      friendly_name: "Average House Pressure"\n'
    )
    start = text.index(marker) + len(marker)
    end = text.index("icon: mdi:gauge", start)
    block = text[start:end]
    assert "device_class: atmospheric_pressure" in block


def test_pressure_trends_group_includes_the_fast_sensors() -> None:
    text = CLIMATE_PATH.read_text(encoding="utf-8")
    start = text.index("pressure_trends:")
    end = text.index("\n\n", start)
    block = text[start:end]
    assert "binary_sensor.pressure_falling_fast" in block
    assert "binary_sensor.pressure_rising_fast" in block


def test_window_pressure_alert_automation_includes_the_fast_sensor() -> None:
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]
    assert "binary_sensor.pressure_falling_fast" in block
    assert "binary_sensor.pressure_falling_quickly" in block
    assert "binary_sensor.pressure_falling_v_rapidly" in block


def test_window_pressure_alert_requires_a_settled_sample_buffer() -> None:
    # Codex P2 follow-up on #974: max_samples only raises the retention cap,
    # it doesn't require a minimum populated duration — every trend sensor
    # still starts with an empty buffer whenever average_house_pressure's
    # own data goes down and comes back, which can be milliseconds apart
    # given average_house_pressure's bursty updates. Require that source to
    # have been available for longer than the shortest (fast, 30-minute)
    # window before trusting any pressure-drop alert.
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]

    assert "input_datetime.pressure_source_available_since" in block
    assert "2100" in block


def test_window_pressure_alert_settle_gate_matches_each_triggers_own_window() -> None:
    # Codex P2 follow-up on #974: a single fixed 35-minute settle wait only
    # covers the fast tier's 30-minute (1800s) window with margin.
    # quickly/v_rapidly use a 3-hour (10800s) window, so the same fixed wait
    # let them fire off a still-mostly-empty buffer for hours after a
    # restart or reconnect. Require each triggering sensor's own window
    # (plus the same 5-minute margin the fast tier already used: 1800+300
    # =2100, 10800+300=11100) instead of one fixed duration for all three.
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]

    assert "11100" in block
    assert "'binary_sensor.pressure_falling_quickly', 11100" in block
    assert "'binary_sensor.pressure_falling_v_rapidly', 11100" in block
    assert "'binary_sensor.pressure_falling_fast', 2100" in block


def test_window_pressure_alert_settle_gate_fails_closed() -> None:
    # Codex P2 follow-up on #974: an unguarded as_timestamp(states(...), 0)
    # would default to epoch 0 while pressure_source_available_since is
    # unknown/unavailable (e.g. before the tracking automation has ever
    # run), making the elapsed-time calculation huge and letting the settle
    # gate pass right when it's needed most. Must require a valid value
    # instead.
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]

    assert "has_value('input_datetime.pressure_source_available_since')" in block
    assert "pressure_source_available_since', 'timestamp'), 0)" not in block
    assert "pressure_source_available_since'), 0)" not in block


def test_pressure_source_available_since_helper_is_defined() -> None:
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    assert "pressure_source_available_since:" in text
    assert "has_date: true" in text


def test_pressure_source_available_since_is_tracked_on_restart_and_reconnect() -> None:
    # Codex P2 follow-up on #974: HA uptime alone only catches the
    # post-restart case. If the pressure source (or its integration)
    # reconnects after an outage while HA stays up, uptime keeps climbing
    # right through the gap even though the trend sensor's history is just
    # as stale — so this must be tracked separately from uptime.
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: track_pressure_source_available_since")
    end = text.index("\n########", start)
    block = text[start:end]

    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert "entity_id: sensor.average_house_pressure" in block
    assert '"unavailable"' in block
    assert '"unknown"' in block
    assert "input_datetime.set_datetime" in block
    assert "input_datetime.pressure_source_available_since" in block


def test_pressure_source_available_since_tracks_each_individual_input() -> None:
    # Codex P2 follow-up on #974: average_house_pressure is a min_max
    # aggregate over 9 individual _tph_pressure sensors and stays numeric
    # as long as at least one input remains available, so a single input
    # dropping out or reconnecting never trips the aggregate's own
    # unavailable/unknown trigger — yet still shifts the aggregate's
    # membership and can produce a discontinuous jump the trend sensors
    # would read as a real, fast pressure change. Must track each of the
    # 9 climate.yaml average_house_pressure entity_ids individually, in
    # both directions (a single input joining or leaving the aggregate).
    climate_path = Path(__file__).resolve().parents[1] / "packages" / "climate.yaml"
    climate_text = climate_path.read_text(encoding="utf-8")
    start = climate_text.index("name: average_house_pressure")
    end = climate_text.index("\n\n", start)
    pressure_inputs_block = climate_text[start:end]
    pressure_inputs = [
        line.strip().removeprefix("- ")
        for line in pressure_inputs_block.splitlines()
        if line.strip().startswith("- sensor.")
    ]
    assert len(pressure_inputs) == 9

    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: track_pressure_source_available_since")
    end = text.index("\n########", start)
    block = text[start:end]

    for entity_id in pressure_inputs:
        assert entity_id in block, f"{entity_id} not tracked individually"

    # One "from" trigger for the aggregate itself (pre-existing) plus one
    # for the individual inputs reconnecting, and one "to" trigger for an
    # individual input disconnecting.
    assert block.count("from:\n          - \"unavailable\"\n          - \"unknown\"") == 2
    assert block.count("to:\n          - \"unavailable\"\n          - \"unknown\"") == 1


def test_window_pressure_alert_rejects_an_implausible_gradient() -> None:
    # Codex P2 follow-up on #974: HA uptime only guards the post-restart
    # case. If the pressure sources or their integration reconnect after an
    # outage longer than the trend window while HA itself stays up, the
    # uptime check already passes but the trend sensor's own history is
    # still fresh off the same clustered updates — a two-sample recovery
    # spike could still fire the alert. A magnitude ceiling on each
    # candidate sensor's own current gradient (not trigger.to_state, which
    # the periodic re-check trigger below doesn't have) catches this
    # regardless of cause (restart, reconnect, or anything else), the same
    # way the derivative clamp in #973/#977 did for temperature.
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]

    assert "state_attr(entity_id, 'gradient')" in block
    assert "* 3600 * 33.8639 <= 15" in block
    assert "trigger.to_state.attributes.gradient" not in block


def test_window_pressure_alert_rechecks_periodically_to_catch_a_mid_window_trend() -> None:
    # Codex P2 follow-up on #974: the original off->on state trigger
    # discards its run if it fires while the settle/gradient conditions are
    # still false, and being a plain edge trigger it won't fire again while
    # the sensor stays on — so a genuine trend that began during the settle
    # window and is still active once it ends would never send the alert.
    weather_path = Path(__file__).resolve().parents[1] / "packages" / "weather.yaml"
    text = weather_path.read_text(encoding="utf-8")
    start = text.index("id: alert_house_windows_open_pressure_dropping")
    end = text.index("\n  - id:", start)
    block = text[start:end]

    assert "trigger: time_pattern" in block
    assert 'minutes: "/5"' in block
    assert "* 3600 * 33.8639 <= 15" in block
