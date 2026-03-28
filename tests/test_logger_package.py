from pathlib import Path


LOGGER_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "packages" / "logger.yaml"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "configuration.yaml"


def test_logger_package_exposes_runtime_esphome_debug_toggle() -> None:
    text = LOGGER_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "input_boolean.esphome_debug_logging" in text
    assert "name: ESPHome Debug Logging" in text
    assert "id: esphome_debug_logging" in text
    assert "trigger: homeassistant" in text
    assert "entity_id:\n          - input_boolean.esphome_debug_logging" in text

    for logger_name in (
        "homeassistant.components.esphome",
        "homeassistant.components.zeroconf",
        "homeassistant.config_entries",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_registry",
        "aioesphomeapi",
        "zeroconf",
    ):
        assert f'{logger_name}: "{{{{ esphome_debug_level }}}}"' in text


def test_logger_package_traces_tikiroom_entity_availability_changes() -> None:
    text = LOGGER_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "id: tikiroom_esphome_availability_trace" in text
    assert "mode: queued" in text
    assert "entity_id: input_boolean.esphome_debug_logging" in text
    assert 'state: "on"' in text
    assert "action: system_log.write" in text
    assert "logger: packages.logger.tikiroom_esphome" in text

    for entity_id in (
        "light.tiki_room_lights_tiki_room_strip",
        "select.tiki_room_lights_tiki_room_strip_effect",
        "number.tiki_room_lights_tiki_room_strip_animation_speed",
        "update.tikiroomlights_firmware",
        "device_tracker.tikiroom_esp8266_led_string",
    ):
        assert entity_id in text


def test_logger_package_enables_system_log_for_tikiroom_trace() -> None:
    config_text = CONFIG_PATH.read_text(encoding="utf-8")

    assert "\nsystem_log:\n" in config_text
