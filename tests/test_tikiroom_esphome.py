from pathlib import Path


TIKIROOM_ESPHOME_PATH = Path(__file__).resolve().parents[1] / "esphome" / "tikiroom.yaml"


def test_tikiroom_esphome_logs_connectivity_lifecycle() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "tag: tikiroom.net" in text
    assert 'format: "WiFi connected to %s"' in text
    assert 'format: "WiFi disconnected with status=%d"' in text
    assert "tag: tikiroom.api" in text
    assert 'format: "API client %s connected from %s"' in text
    assert 'format: "API client %s disconnected from %s"' in text


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


def test_tikiroom_esphome_limits_frame_rate_for_gpio14_bit_bang() -> None:
    text = TIKIROOM_ESPHOME_PATH.read_text(encoding="utf-8")

    assert "tikiroom_effect_frame_interval: 50ms" in text
    assert "restore_mode: ALWAYS_OFF" in text
    assert text.count("update_interval: ${tikiroom_effect_frame_interval}") == 19
