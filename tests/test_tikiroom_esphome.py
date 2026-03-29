from pathlib import Path


TIKIROOM_ESPHOME_PATH = Path(__file__).resolve().parents[1] / "esphome" / "tikiroom.yaml"


def test_tikiroom_esphome_uses_native_api_without_extra_trace_hooks() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "\napi:\n  reboot_timeout: 15min\n" in text
    assert "tikiroom_api" not in text
    assert "tag: tikiroom.api" not in text
    assert "tag: tikiroom.net" not in text
    assert "logger.log:" not in text


def test_tikiroom_esphome_removes_boot_and_runtime_debug_instrumentation() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "on_boot:" not in text
    assert "\ninterval:\n" not in text
    assert "tag: tikiroom.boot" not in text
    assert "state_subscription_only: true" not in text


def test_tikiroom_esphome_does_not_expose_tikiroom_debug_entities() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "\ndebug:\n" not in text
    assert "\nbinary_sensor:\n" not in text
    assert '- platform: wifi_signal' not in text
    assert '- platform: debug' not in text
    assert '- platform: wifi_info' not in text


def test_tikiroom_esphome_keeps_user_controls_without_log_side_effects() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert 'name: "Tiki Room Strip Animation Speed"' in text
    assert 'name: "Tiki Room Strip Effect"' in text
    assert 'name: "Tiki Room Strip"' in text
    assert 'format: "Animation speed changed to %.0f"' not in text
    assert 'format: "Effect changed to %s"' not in text
    assert 'format: "Light turned on with effect %s"' not in text


def test_tikiroom_esphome_exposes_f1_race_effect() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "- f1 race" in text
    assert "name: f1 race" in text
    assert "tikiroom::apply_f1_race(it, id(tikiroom_effect_speed), initial_run);" in text


def test_tikiroom_esphome_exposes_atmospheric_effects() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "- lava field" in text
    assert "name: lava field" in text
    assert "tikiroom::apply_lava_field(it, id(tikiroom_effect_speed), initial_run);" in text

    assert "- thunderstorm" in text
    assert "name: thunderstorm" in text
    assert "tikiroom::apply_thunderstorm(it, id(tikiroom_effect_speed), initial_run);" in text

    assert "- wall fire" in text
    assert "name: wall fire" in text
    assert "tikiroom::apply_wall_fire(it, id(tikiroom_effect_speed), initial_run);" in text


def test_tikiroom_esphome_limits_frame_rate_for_gpio14_bit_bang() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "tikiroom_effect_frame_interval: 50ms" in text
    assert "restore_mode: ALWAYS_OFF" in text
    assert text.count("update_interval: ${tikiroom_effect_frame_interval}") == 23
