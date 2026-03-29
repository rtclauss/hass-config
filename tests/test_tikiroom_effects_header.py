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
    assert "constexpr uint8_t GLITTER_FADE_AMOUNT = 20;" in text
    assert "constexpr size_t LAVA_FIELD_CELLS = 48;" in text
    assert "constexpr size_t THUNDERSTORM_CELLS = 40;" in text
    assert "inline void add_scaled_inplace(Color &base, const Color &added, uint8_t scale)" in text
    assert "inline Color sample_coarse_cells(const std::array<Color, CELL_COUNT> &cells, uint16_t led_index)" in text


def test_lava_field_layers_heat_and_uses_fade_carryover() -> None:
    block = _function_block("apply_lava_field")

    assert "std::array<Color, LAVA_FIELD_CELLS> lava_cells{};" in block
    assert "cluster_phases" in block
    assert "cluster_radii" in block
    assert "clump_heat" in block
    assert "ember_wave" in block
    assert "fade_to_black(GLITTER_FADE_AMOUNT);" in block
    assert "smoothstep(0.18f, 0.96f, molten_mix)" in block
    assert "lava_cells[cell] = pixel;" in block
    assert "add_scaled_inplace(rt.leds[i], sample_coarse_cells(lava_cells, i), GLITTER_FADE_AMOUNT);" in block


def test_thunderstorm_uses_jungle_canopy_palette_and_fade_carryover() -> None:
    block = _function_block("apply_thunderstorm")

    assert "foliage_phases" in block
    assert "rain_phases" in block
    assert "std::array<Color, THUNDERSTORM_CELLS> ambient_cells{};" in block
    assert "fade_to_black(GLITTER_FADE_AMOUNT);" in block
    assert "ambient_cells[cell] = pixel;" in block
    assert "rain_group" in block
    assert "add_scaled_inplace(rt.leds[i], sample_coarse_cells(ambient_cells, i), GLITTER_FADE_AMOUNT);" in block
    assert "add_scaled_inplace(rt.leds[i], flash_overlay, 88);" in block


def test_f1_race_can_trigger_random_overtakes() -> None:
    block = _function_block("apply_f1_race")

    assert "static uint32_t last_motion_ms = 0;" in block
    assert "static uint32_t next_overtake_ms = 0;" in block
    assert "static std::array<float, 5> car_progress{};" in block
    assert "static std::array<float, 5> pace_delta{};" in block
    assert "car_progress[i] += delta_s * laps_per_second * effective_pace[i];" in block
    assert "const uint8_t attacker = random_u8(static_cast<uint8_t>(cars.size()));" in block
    assert "pace_delta[attacker] += attack_boost;" in block
