from pathlib import Path


LOGGER_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "packages" / "logger.yaml"


def test_logger_package_exposes_runtime_log_level_control() -> None:
    text = LOGGER_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "automation.log_level" in text
    assert "input_select:\n  log_level:" in text
    assert "id: log_level" in text
    assert "entity_id:\n          - input_select.log_level" in text
    assert 'homeassistant.components: "{{ states.input_select.log_level.state }}"' in text


def test_logger_package_does_not_keep_tikiroom_esphome_debug_helpers() -> None:
    text = LOGGER_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "input_boolean.esphome_debug_logging" not in text
    assert "id: esphome_debug_logging" not in text
    assert "id: tikiroom_esphome_availability_trace" not in text
    assert "packages.logger.tikiroom_esphome" not in text
