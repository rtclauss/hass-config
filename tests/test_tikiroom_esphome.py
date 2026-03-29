from pathlib import Path


TIKIROOM_ESPHOME_PATH = Path(__file__).resolve().parents[1] / "esphome" / "tikiroom.yaml"


def test_tikiroom_esphome_logs_connectivity_lifecycle() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "tag: tikiroom.net" in text
    assert 'format: "WiFi connected to %s"' in text
    assert 'format: "WiFi disconnected with status=%d"' in text
    assert "id: tikiroom_api" in text
    assert "tag: tikiroom.api" in text
    assert 'format: "API client %s connected from %s (state_subscriber=%s)"' in text
    assert 'format: "State-subscribing API client connected; Home Assistant should be able to control entities"' in text
    assert 'format: "API client connected without state subscription; entity registration is still pending"' in text
    assert 'format: "API client %s disconnected from %s (state_subscriber=%s)"' in text
    assert 'format: "No state-subscribing API clients remain; Home Assistant entities will go unavailable"' in text


def test_tikiroom_esphome_logs_boot_and_registration_stages() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "tag: tikiroom.boot" in text
    assert 'format: "Boot stage=hardware priority=800"' in text
    assert 'format: "Boot stage=wifi priority=250 wifi_status=%d"' in text
    assert 'format: "Boot stage=api priority=200 wifi_status=%d api_any=%s api_state_sub=%s"' in text
    assert 'format: "Boot stage=ready priority=-100 effect=%s speed=%.0f api_any=%s api_state_sub=%s"' in text
    assert 'format: "Waiting up to 30s for a state-subscribing API client so entities can register"' in text
    assert "wait_until:" in text
    assert "state_subscription_only: true" in text
    assert "timeout: 30s" in text
    assert 'format: "State-subscribing API client connected; entity registration should now be active"' in text
    assert 'format: "No state-subscribing API client connected within 30s; entities will remain unavailable"' in text
    assert "startup_delay: 45s" in text
    assert 'format: "Runtime registration check missing state-subscribing API client; wifi_status=%d api_any=%s effect=%s speed=%.0f"' in text


def test_tikiroom_esphome_exposes_diagnostic_entities() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "debug:\n  update_interval: 60s" in text
    assert "- platform: status" in text
    assert '- platform: wifi_signal' in text
    assert '- platform: debug' in text
    assert '- platform: wifi_info' in text

    for entity_name in (
        "Tiki Room Strip Status",
        "Tiki Room Strip WiFi Signal",
        "Tiki Room Strip Heap Free",
        "Tiki Room Strip Heap Max Block",
        "Tiki Room Strip Heap Fragmentation",
        "Tiki Room Strip Loop Time",
        "Tiki Room Strip IP Address",
        "Tiki Room Strip Connected SSID",
        "Tiki Room Strip Connected BSSID",
        "Tiki Room Strip Reset Reason",
    ):
        assert f'name: "{entity_name}"' in text


def test_tikiroom_esphome_logs_light_commands() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert 'format: "Animation speed changed to %.0f"' in text
    assert 'format: "Effect changed to %s"' in text
    assert 'format: "Light turned on with effect %s"' in text
    assert 'format: "Light turned off"' in text
    assert 'format: "Light state updated; active effect %s"' in text


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
