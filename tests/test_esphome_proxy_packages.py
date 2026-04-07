from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ESPHOME_DIR = REPO_ROOT / "esphome"
BASE_PACKAGE_PATH = ESPHOME_DIR / "packages" / "common" / "base.yaml"
BLUETOOTH_PROXY_PACKAGE_PATH = ESPHOME_DIR / "packages" / "common" / "bluetooth_proxy.yaml"
PROXY_CONFIG_PATHS = (
    ESPHOME_DIR / "bluetoothproxy1.yaml",
    ESPHOME_DIR / "livingroombtproxy.yaml",
    ESPHOME_DIR / "office-bt-proxy.yaml",
)


def test_ble_proxies_use_shared_base_and_bluetooth_proxy_packages() -> None:
    for path in PROXY_CONFIG_PATHS:
        text = path.read_text(encoding="utf-8")

        assert "packages:" in text
        assert "common_base: !include packages/common/base.yaml" in text
        assert "bluetooth_proxy: !include packages/common/bluetooth_proxy.yaml" in text
        assert "\nwifi:\n" not in text
        assert "\napi:\n" not in text
        assert "\nota:\n" not in text
        assert "\nbluetooth_proxy:\n" not in text
        assert "\ndashboard_import:\n" not in text


def test_shared_base_package_exposes_standard_diagnostics() -> None:
    text = BASE_PACKAGE_PATH.read_text(encoding="utf-8")

    assert 'name: "${device_label} Status"' in text
    assert "- platform: uptime" in text
    assert 'name: "${device_label} Uptime"' in text
    assert "- platform: wifi_signal" in text
    assert 'name: "${device_label} WiFi Signal"' in text
    assert "- platform: version" in text
    assert 'name: "${device_label} ESPHome Version"' in text
    assert "- platform: wifi_info" in text
    assert 'name: "${device_label} IP Address"' in text
    assert 'name: "${device_label} MAC Address"' in text


def test_shared_bluetooth_proxy_package_keeps_recommended_minimal_proxy_stack() -> None:
    text = BLUETOOTH_PROXY_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "framework:\n    type: esp-idf" in text
    assert "scan_parameters:\n    active: true" in text
    assert "\nbluetooth_proxy:\n  active: true\n" in text
    assert "\nxiaomi_ble:\n" in text
    assert "interval:" not in text
    assert "window:" not in text
    assert "connection_slots:" not in text
    assert "\nesp32_ble:\n" not in text


def test_office_proxy_keeps_apple_watch_presence_logic() -> None:
    text = (ESPHOME_DIR / "office-bt-proxy.yaml").read_text(encoding="utf-8")

    assert "\nesp32_ble_tracker:\n" in text
    assert "on_ble_advertise:" in text
    assert 'name: "$yourname Apple Watch $roomname RSSI"' in text
    assert 'name: "$yourname $roomname presence"' in text
    assert "id: presence_timeout" in text
