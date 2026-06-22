from __future__ import annotations

from pathlib import Path


PARASOLL_PATH = Path(__file__).resolve().parents[1] / "packages" / "parasoll_fix.yaml"


def test_parasoll_configure_state_uses_csv_within_ha_input_text_limit() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "Compact CSV: <last4_ieee>:<mod_hour>,..." in text
    assert "max: 255" in text
    assert 'initial: ""' in text
    assert "{{ ns.pairs | join(',') }}" in text
    assert "| tojson" not in text


def test_parasoll_configure_state_keeps_legacy_json_read_compatibility() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "raw.startswith('{')" in text
    assert "raw | from_json" in text
    assert "store.items()" in text


def test_parasoll_csv_state_has_room_for_current_device_count() -> None:
    device_count = 20
    sample_pairs = [f"{index:04x}:9999" for index in range(device_count)]
    assert len(",".join(sample_pairs)) < 255


def test_parasoll_auto_reconfigure_queue_covers_current_fleet_burst() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "mode: queued" in text
    assert "max: 30" in text
    assert "full fleet burst plus headroom" in text


def test_parasoll_contact_change_ignores_startup_restores() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert 'id: contact_change' in text
    assert 'from:\n          - "on"\n          - "off"' in text
    assert 'to:\n          - "on"\n          - "off"' in text


def test_parasoll_contact_change_keeps_restored_south_middle_contact() -> None:
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "binary_sensor.owner_suite_bathroom_bay_south_middle_window_contact" in text


def test_parasoll_ias_ok_checks_ep2_not_ep1() -> None:
    # PARASOLL's ssIasZone cluster lives on endpoint 2 (confirmed by Z2M Bind tab
    # "Source endpoint 2: ssIasZone").  Checking ep1 would always return False,
    # causing _needs_configure to be True on every contact_change — the original bug.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "_ep2_bindings" in text
    assert "'ssIasZone' in _ep2_bindings" in text
    # Ensure we are NOT using ep1 for the IAS check
    assert "'ssIasZone' in _ep1_bindings" not in text


def test_parasoll_enforce_intervals_clamps_max_to_14400() -> None:
    # The actual drop-off fix (Koenkk/zigbee2mqtt#22579): the factory max report
    # interval of 65000 s lets sleepy sensors be marked offline.  The enforce
    # script must clamp it to 14400 s via Z2M's reporting/configure request.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "parasoll_enforce_intervals:" in text
    assert "zigbee2mqtt/bridge/request/device/reporting/configure" in text
    assert '"maximum_report_interval": 14400' in text


def test_parasoll_enforce_intervals_covers_all_three_attributes() -> None:
    # zoneStatus on ep2 (min 0) plus both battery attrs on ep1 must be clamped.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "attribute: zoneStatus" in text
    assert "attribute: batteryPercentageRemaining" in text
    assert "attribute: batteryVoltage" in text
    assert "cluster: ssIasZone" in text
    assert "cluster: genPowerCfg" in text


def test_parasoll_enforce_intervals_invoked_by_script_and_automation() -> None:
    # Both the bulk reconfigure script and the join/announce automation must call
    # the shared enforce script so already-joined and newly-joined sensors converge.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert text.count("script.parasoll_enforce_intervals") >= 2


def test_parasoll_needs_configure_checks_reporting_interval() -> None:
    # The interval must be a configuration invariant, otherwise already-joined
    # devices at the factory 65000 s default would never be reconfigured.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "_interval_ok" in text
    assert "not _interval_ok" in text


def test_parasoll_auto_reconfigure_has_per_device_rate_limit() -> None:
    # A rejoin-looping sensor previously fired the automation on every announce,
    # flooding the coordinator with timing-out binds and overflowing the queue.
    # The first action must throttle each device to ~1 configure/hour.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "_rl_hours_since" in text
    assert '"{{ _rl_hours_since | int >= 1 }}"' in text


def test_parasoll_rate_limit_runs_before_any_configure() -> None:
    # The gate is only a circuit breaker if it exits BEFORE the delay, the
    # bridge/devices wait, and the bind/configure MQTT requests.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    gate = text.index("_rl_hours_since")
    # rindex: the automation's own unbind/configure (the script's appear earlier
    # in the file, before the automation block and thus before the gate).
    assert gate < text.rindex("zigbee2mqtt/bridge/request/device/unbind")
    assert gate < text.rindex("zigbee2mqtt/bridge/request/device/configure")
    # And before the action-block delay that waits on sleepy devices.
    assert gate < text.index("5000 if trigger.id == 'bridge_event'")


def test_parasoll_matches_stock_model_not_patched_converter() -> None:
    # The external converter has been removed; devices report the stock model
    # description "PARASOLL door/window sensor".  Matching the old "(patched)"
    # string would silently match zero devices and the fix would stop applying.
    text = PARASOLL_PATH.read_text(encoding="utf-8")

    assert "(patched)" not in text
    assert "'model') == 'PARASOLL door/window sensor'" in text
