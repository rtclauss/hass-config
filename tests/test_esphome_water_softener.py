from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CONFIG = ROOT / "esphome" / "watersoftener.yaml"
LEGACY_CONFIG = (
    ROOT / "docs" / "esphome_archive" / "watersoftener-esp8266-vl53l0x.yaml"
)
HA_PACKAGE = ROOT / "packages" / "water_softener.yaml"


def test_legacy_water_softener_configuration_is_archived() -> None:
    text = LEGACY_CONFIG.read_text(encoding="utf-8")

    assert "esp8266:" in text
    assert "board: esp01_1m" in text
    assert "platform: vl53l0x" in text
    assert 'name: "My Water Softener VL53L0X Sensor"' in text


def test_active_water_softener_uses_esp32_and_pinned_vl53l1x_component() -> None:
    text = ACTIVE_CONFIG.read_text(encoding="utf-8")

    assert "esp32:" in text
    assert "variant: esp32" in text
    assert "type: esp-idf" in text
    assert 'minimum_chip_revision: "3.0"' in text
    assert "sram1_as_iram: true" in text
    assert "github://soldierkam/vl53l1x_sensor@v0.5.1" in text
    assert "platform: vl53l1x_sensor" in text
    assert "platform: vl53l0x" not in text
    assert 'name: "My Water Softener VL53L1X Sensor"' in text


def test_vl53l1x_wiring_and_measurement_contract_are_explicit() -> None:
    text = ACTIVE_CONFIG.read_text(encoding="utf-8")

    assert "sda: GPIO21" in text
    assert "scl: GPIO22" in text
    assert "frequency: 400kHz" in text
    assert "address: 0x29" in text
    assert "distance_mode: LONG" in text
    assert "timing_budget: 200ms" in text
    assert "unit_of_measurement: \"mm\"" in text
    assert "accuracy_decimals: 0" in text
    assert "lambda: return x * 1000;" in text
    assert "update_interval: 2s" in text


def test_home_assistant_package_consumes_new_sensor_entity() -> None:
    text = HA_PACKAGE.read_text(encoding="utf-8")

    assert "entity_id: sensor.my_water_softener_vl53l1x_sensor" in text
    assert "entity_id: sensor.my_water_softener_vl53l0x_sensor" not in text
