from pathlib import Path


TIKIROOM_EFFECTS_HEADER_PATH = Path(__file__).resolve().parents[1] / "esphome" / "tikiroom_effects.h"


def _function_block(name: str) -> str:
    text = TIKIROOM_EFFECTS_HEADER_PATH.read_text(encoding="utf-8")
    start = text.index(f"inline void {name}(")
    end = text.find("\ninline void ", start + 1)
    if end == -1:
        end = len(text)
    return text[start:end]


def test_tikiroom_effects_header_exposes_smoothing_helper() -> None:
    text = TIKIROOM_EFFECTS_HEADER_PATH.read_text(encoding="utf-8")

    assert "inline float smoothstep(float edge0, float edge1, float value)" in text


def test_lava_field_layers_heat_and_blends_frames() -> None:
    block = _function_block("apply_lava_field")

    assert "base_flow" in block
    assert "ember_wave" in block
    assert "smoothstep(0.22f, 0.94f, molten_mix)" in block
    assert "rt.leds[i] = blend(rt.leds[i], pixel, 92);" in block


def test_thunderstorm_uses_jungle_canopy_palette_and_frame_blending() -> None:
    block = _function_block("apply_thunderstorm")

    assert "canopy_offset" in block
    assert "const float canopy =" in block
    assert "const float undergrowth =" in block
    assert "const Color storm_haze(" in block
    assert "rt.leds[i] = blend(rt.leds[i], pixel, 108);" in block
