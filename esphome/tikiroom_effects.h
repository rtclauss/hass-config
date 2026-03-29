#pragma once

#include <array>
#include <cmath>
#include <cstdint>

#include "esphome/components/light/addressable_light.h"
#include "esphome/core/color.h"

namespace tikiroom {

using esphome::Color;
using esphome::light::AddressableLight;

constexpr uint16_t NUM_LEDS = 579;
constexpr uint8_t DENSITY = 80;
constexpr uint8_t MAX_RIPPLE_STEPS = 16;
constexpr uint8_t COOLING = 55;
constexpr uint8_t SPARKING = 120;
constexpr float PI_F = 3.14159265f;

struct RuntimeState {
  std::array<Color, NUM_LEDS> leds{};
  std::array<uint8_t, NUM_LEDS> heat{};
  uint8_t rainbow_hue{0};
  uint8_t g_hue{0};
  uint16_t noise_dist{0};
  std::array<Color, 4> current_palette{};
  std::array<Color, 4> target_palette{};
};

inline RuntimeState &state() {
  static RuntimeState instance{
      {},
      {},
      0,
      0,
      0,
      {Color(0, 0, 40), Color(0, 80, 120), Color(0, 160, 200), Color(0, 220, 255)},
      {Color(0, 0, 40), Color(0, 80, 120), Color(0, 160, 200), Color(0, 220, 255)},
  };
  return instance;
}

inline uint32_t now_ms() { return millis(); }

inline uint8_t random_u8() { return static_cast<uint8_t>(random(256)); }

inline uint8_t random_u8(uint8_t max_value) { return max_value == 0 ? 0 : static_cast<uint8_t>(random(max_value)); }

inline uint8_t random_u8(uint8_t min_value, uint8_t max_value) {
  if (max_value <= min_value) {
    return min_value;
  }
  return static_cast<uint8_t>(random(min_value, max_value));
}

inline uint16_t random_u16(uint16_t max_value) {
  if (max_value == 0) {
    return 0;
  }
  return static_cast<uint16_t>(random(max_value));
}

inline uint8_t clamp_u8(int value) {
  if (value < 0) {
    return 0;
  }
  if (value > 255) {
    return 255;
  }
  return static_cast<uint8_t>(value);
}

inline uint32_t clamp_interval(float speed, uint32_t slow_ms = 120, uint32_t fast_ms = 10) {
  if (speed < 1.0f) {
    speed = 1.0f;
  } else if (speed > 150.0f) {
    speed = 150.0f;
  }
  const float ratio = (speed - 1.0f) / 149.0f;
  return static_cast<uint32_t>(slow_ms - ((slow_ms - fast_ms) * ratio));
}

inline bool due(uint32_t &last_update, uint32_t interval_ms) {
  const auto now = now_ms();
  if (last_update == 0 || (now - last_update) >= interval_ms) {
    last_update = now;
    return true;
  }
  return false;
}

inline Color blend(const Color &a, const Color &b, uint8_t amount) {
  const auto inv = static_cast<uint8_t>(255 - amount);
  return Color(
      static_cast<uint8_t>((a.r * inv + b.r * amount) / 255),
      static_cast<uint8_t>((a.g * inv + b.g * amount) / 255),
      static_cast<uint8_t>((a.b * inv + b.b * amount) / 255));
}

inline void add_inplace(Color &base, const Color &added) {
  base.r = clamp_u8(base.r + added.r);
  base.g = clamp_u8(base.g + added.g);
  base.b = clamp_u8(base.b + added.b);
}

inline Color scale_color(const Color &color, uint8_t scale) {
  return Color(
      static_cast<uint8_t>((color.r * scale) / 255),
      static_cast<uint8_t>((color.g * scale) / 255),
      static_cast<uint8_t>((color.b * scale) / 255));
}

inline Color hsv_to_rgb(uint8_t h, uint8_t s, uint8_t v) {
  if (s == 0) {
    return Color(v, v, v);
  }

  const uint8_t region = h / 43;
  const uint8_t remainder = (h - (region * 43)) * 6;

  const uint8_t p = (v * (255 - s)) >> 8;
  const uint8_t q = (v * (255 - ((s * remainder) >> 8))) >> 8;
  const uint8_t t = (v * (255 - ((s * (255 - remainder)) >> 8))) >> 8;

  switch (region) {
    case 0:
      return Color(v, t, p);
    case 1:
      return Color(q, v, p);
    case 2:
      return Color(p, v, t);
    case 3:
      return Color(p, q, v);
    case 4:
      return Color(t, p, v);
    default:
      return Color(v, p, q);
  }
}

inline uint8_t sin8_from_phase(float phase) {
  return static_cast<uint8_t>(((std::sin(phase) + 1.0f) * 0.5f) * 255.0f);
}

inline uint8_t beatsin8(uint8_t bpm, uint8_t low, uint8_t high, float offset = 0.0f) {
  const float phase = ((now_ms() / 1000.0f) * bpm / 60.0f * 2.0f * PI_F) + offset;
  const float wave = (std::sin(phase) + 1.0f) * 0.5f;
  return static_cast<uint8_t>(low + wave * (high - low));
}

inline uint16_t beatsin16(uint8_t bpm, uint16_t low, uint16_t high, float offset = 0.0f) {
  const float phase = ((now_ms() / 1000.0f) * bpm / 60.0f * 2.0f * PI_F) + offset;
  const float wave = (std::sin(phase) + 1.0f) * 0.5f;
  return static_cast<uint16_t>(low + wave * (high - low));
}

inline float pseudo_noise(uint16_t x, uint16_t y) {
  const float xf = static_cast<float>(x) * 0.11f;
  const float yf = static_cast<float>(y) * 0.015f;
  const float n =
      std::sin(xf + yf) +
      std::sin((xf * 0.31f) - (yf * 1.77f)) +
      std::sin((xf * 1.13f) + (yf * 0.53f));
  return (n + 3.0f) / 6.0f;
}

inline Color palette_color(const std::array<Color, 4> &palette, uint8_t index) {
  const uint8_t segment = index / 64;
  const uint8_t amount = (index % 64) * 4;
  const auto &a = palette[segment];
  const auto &b = palette[(segment + 1) % palette.size()];
  return blend(a, b, amount);
}

inline const std::array<Color, 4> &candy_cane_palette() {
  static const std::array<Color, 4> palette{
      Color(255, 0, 0), Color(255, 0, 0), Color(255, 255, 255), Color(255, 255, 255)};
  return palette;
}

inline const std::array<Color, 4> &christmas_palette() {
  static const std::array<Color, 4> palette{
      Color(255, 0, 0), Color(255, 0, 0), Color(0, 255, 0), Color(0, 255, 0)};
  return palette;
}

inline const std::array<Color, 4> &party_palette() {
  static const std::array<Color, 4> palette{
      Color(140, 0, 255), Color(0, 96, 255), Color(0, 255, 220), Color(255, 0, 128)};
  return palette;
}

inline Color heat_color(uint8_t heat) {
  if (heat <= 85) {
    return blend(Color(0, 0, 0), Color(255, 0, 0), heat * 3);
  }
  if (heat <= 170) {
    return blend(Color(255, 0, 0), Color(255, 160, 0), (heat - 85) * 3);
  }
  return blend(Color(255, 160, 0), Color(255, 255, 255), (heat - 170) * 3);
}

inline void copy_to_output(AddressableLight &it) {
  auto &rt = state();
  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    it[i] = rt.leds[i];
  }
}

inline void fill_all(const Color &color) {
  state().leds.fill(color);
}

inline void clear_leds() { fill_all(Color(0, 0, 0)); }

inline void fade_to_black(uint8_t amount) {
  const uint8_t scale = 255 - amount;
  for (auto &led : state().leds) {
    led = scale_color(led, scale);
  }
}

inline void nscale8(uint8_t scale) {
  for (auto &led : state().leds) {
    led = scale_color(led, scale);
  }
}

inline void add_glitter(uint8_t chance, const Color &color) {
  if (random_u8() < chance) {
    add_inplace(state().leds[random_u16(NUM_LEDS)], color);
  }
}

inline uint16_t wrap_led_index(int32_t index) {
  const auto led_count = static_cast<int32_t>(NUM_LEDS);
  index %= led_count;
  if (index < 0) {
    index += led_count;
  }
  return static_cast<uint16_t>(index);
}

inline void fill_rainbow(uint8_t start_hue, uint8_t delta_hue) {
  auto &rt = state();
  uint8_t hue = start_hue;
  for (auto &led : rt.leds) {
    led = hsv_to_rgb(hue, 255, 255);
    hue += delta_hue;
  }
}

inline void fill_palette_stripes(const std::array<Color, 4> &palette, uint8_t start_index) {
  auto &rt = state();
  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    const uint8_t pos = static_cast<uint8_t>((start_index + (i * 16)) & 0xFF);
    rt.leds[i] = palette_color(palette, pos);
  }
}

inline void apply_solid(AddressableLight &it, const Color &current_color, bool initial_run) {
  if (initial_run) {
    clear_leds();
  }
  fill_all(current_color);
  copy_to_output(it);
}

inline void apply_bpm(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    rt.g_hue = 0;
  }
  if (!due(last_update, clamp_interval(speed, 80, 12))) {
    copy_to_output(it);
    return;
  }
  const uint8_t beat = beatsin8(62, 64, 255);
  const auto &palette = party_palette();
  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    const uint8_t index = static_cast<uint8_t>(rt.g_hue + (i * 2));
    const uint8_t brightness = static_cast<uint8_t>(beat - rt.g_hue + (i * 10));
    rt.leds[i] = scale_color(palette_color(palette, index), brightness);
  }
  rt.g_hue++;
  copy_to_output(it);
}

inline void apply_candy_cane(AddressableLight &it, float speed, const std::array<Color, 4> &palette, bool initial_run) {
  static uint8_t start_index = 0;
  static uint32_t last_update = 0;
  if (initial_run) {
    start_index = 0;
  }
  if (!due(last_update, clamp_interval(speed, 100, 16))) {
    copy_to_output(it);
    return;
  }
  fill_palette_stripes(palette, start_index);
  start_index++;
  copy_to_output(it);
}

inline void apply_confetti(AddressableLight &it, const Color &current_color, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 100, 12))) {
    copy_to_output(it);
    return;
  }
  fade_to_black(25);
  auto burst = current_color;
  burst.r = clamp_u8(burst.r + random_u8(64));
  add_inplace(rt.leds[random_u16(NUM_LEDS)], burst);
  copy_to_output(it);
}

inline void apply_cyclon_rainbow(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  static uint16_t position = 0;
  static int8_t direction = 1;
  static uint8_t hue = 0;
  auto &rt = state();
  if (initial_run) {
    position = 0;
    direction = 1;
    hue = 0;
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 80, 8))) {
    copy_to_output(it);
    return;
  }
  nscale8(250);
  rt.leds[position] = hsv_to_rgb(hue++, 255, 255);
  if (direction > 0) {
    if (position >= (NUM_LEDS - 1)) {
      direction = -1;
      position = NUM_LEDS - 1;
    } else {
      position++;
    }
  } else if (position == 0) {
    direction = 1;
  } else {
    position--;
  }
  copy_to_output(it);
}

inline void apply_dots(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 70, 10))) {
    copy_to_output(it);
    return;
  }
  const uint16_t inner = beatsin16(30, NUM_LEDS / 4, (NUM_LEDS / 4) * 3);
  const uint16_t outer = beatsin16(30, 0, NUM_LEDS - 1, 1.5f);
  const uint16_t middle = beatsin16(30, NUM_LEDS / 3, (NUM_LEDS / 3) * 2, 3.0f);
  rt.leds[middle] = Color(160, 0, 255);
  rt.leds[inner] = Color(0, 80, 255);
  rt.leds[outer] = Color(0, 220, 255);
  nscale8(224);
  copy_to_output(it);
}

inline void apply_fire(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    rt.heat.fill(0);
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 90, 16))) {
    copy_to_output(it);
    return;
  }
  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    const uint8_t cooldown = random_u8(0, ((COOLING * 10) / NUM_LEDS) + 2);
    rt.heat[i] = rt.heat[i] > cooldown ? rt.heat[i] - cooldown : 0;
  }
  for (int k = NUM_LEDS - 1; k >= 2; k--) {
    rt.heat[k] = static_cast<uint8_t>((rt.heat[k - 1] + rt.heat[k - 2] + rt.heat[k - 2]) / 3);
  }
  if (random_u8() < SPARKING) {
    const uint8_t y = random_u8(7);
    rt.heat[y] = clamp_u8(rt.heat[y] + random_u8(160, 255));
  }
  for (uint16_t j = 0; j < NUM_LEDS; j++) {
    rt.leds[j] = heat_color(rt.heat[j]);
  }
  copy_to_output(it);
}

inline void apply_f1_race(AddressableLight &it, float speed, bool initial_run) {
  struct CarSpec {
    Color color;
    float base_pace;
    float start_offset;
    float variation_rate;
    float variation_amount;
  };

  static const std::array<CarSpec, 5> cars{{
      {Color(255, 32, 32), 1.00f, 0.00f, 0.55f, 0.018f},
      {Color(255, 140, 0), 0.99f, 0.19f, 0.47f, 0.016f},
      {Color(0, 180, 255), 0.98f, 0.38f, 0.61f, 0.021f},
      {Color(0, 96, 255), 1.01f, 0.57f, 0.43f, 0.014f},
      {Color(0, 220, 120), 0.97f, 0.76f, 0.52f, 0.019f},
  }};

  static uint32_t last_update = 0;
  static uint32_t race_start_ms = 0;
  auto &rt = state();

  if (initial_run) {
    race_start_ms = now_ms();
    clear_leds();
  }

  if (!due(last_update, clamp_interval(speed, 90, 14))) {
    copy_to_output(it);
    return;
  }

  if (race_start_ms == 0) {
    race_start_ms = now_ms();
  }

  const float elapsed_s = (now_ms() - race_start_ms) / 1000.0f;
  const float laps_per_second = 0.025f + ((speed / 150.0f) * 0.110f);
  const uint8_t tarmac_level = beatsin8(10, 6, 12);

  fill_all(Color(tarmac_level, tarmac_level, tarmac_level));

  for (uint16_t i = 12; i < NUM_LEDS; i += 24) {
    rt.leds[i] = Color(20, 20, 20);
  }

  for (uint8_t i = 0; i < 10; i++) {
    rt.leds[i] = (i % 2 == 0) ? Color(60, 60, 60) : Color(4, 4, 4);
  }

  for (uint8_t i = 0; i < 5; i++) {
    const uint8_t brightness = static_cast<uint8_t>(((std::sin((elapsed_s * 2.3f) - (i * 0.45f)) + 1.0f) * 0.5f) * 170.0f);
    rt.leds[wrap_led_index(16 + (i * 3))] = Color(brightness, 0, 0);
  }

  const uint16_t sector_one = NUM_LEDS / 3;
  const uint16_t sector_two = (NUM_LEDS * 2) / 3;
  for (uint8_t i = 0; i < 6; i++) {
    rt.leds[wrap_led_index(sector_one + i)] = Color(0, 80, 0);
    rt.leds[wrap_led_index(sector_two + i)] = Color(110, 0, 110);
  }

  for (const auto &car : cars) {
    const float variation = std::sin((elapsed_s * car.variation_rate * 2.0f * PI_F) + (car.start_offset * 2.0f * PI_F));
    const float progress = (elapsed_s * laps_per_second * car.base_pace) + car.start_offset + (variation * car.variation_amount);
    const int32_t nose = static_cast<int32_t>(progress * NUM_LEDS);

    add_inplace(rt.leds[wrap_led_index(nose)], Color(255, 255, 255));
    add_inplace(rt.leds[wrap_led_index(nose - 1)], scale_color(car.color, 255));
    add_inplace(rt.leds[wrap_led_index(nose - 2)], scale_color(car.color, 192));
    add_inplace(rt.leds[wrap_led_index(nose - 3)], scale_color(car.color, 128));
    add_inplace(rt.leds[wrap_led_index(nose - 4)], scale_color(car.color, 72));
    add_inplace(rt.leds[wrap_led_index(nose - 5)], scale_color(car.color, 32));
  }

  copy_to_output(it);
}

inline void apply_glitter(AddressableLight &it, const Color &current_color, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  if (initial_run) {
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 90, 12))) {
    copy_to_output(it);
    return;
  }
  fade_to_black(20);
  add_glitter(80, current_color);
  copy_to_output(it);
}

inline void apply_juggle(AddressableLight &it, const Color &current_color, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 90, 12))) {
    copy_to_output(it);
    return;
  }
  fade_to_black(20);
  for (int i = 0; i < 8; i++) {
    add_inplace(rt.leds[beatsin16(i + 7, 0, NUM_LEDS - 1, i)], current_color);
  }
  copy_to_output(it);
}

inline void apply_lightning(AddressableLight &it, float speed, bool initial_run) {
  static bool active = false;
  static uint8_t flashes_remaining = 0;
  static uint8_t flash_index = 0;
  static bool segment_on = false;
  static uint32_t next_step_ms = 0;
  static uint32_t next_strike_ms = 0;
  static uint16_t led_start = 0;
  static uint16_t led_len = 1;
  auto &rt = state();
  const auto now = now_ms();

  if (initial_run) {
    active = false;
    flashes_remaining = 0;
    flash_index = 0;
    segment_on = false;
    next_step_ms = 0;
    next_strike_ms = now + 1000;
    clear_leds();
  }

  if (!active && now >= next_strike_ms) {
    active = true;
    flashes_remaining = random_u8(3, 8);
    flash_index = 0;
    segment_on = true;
    led_start = random_u16(NUM_LEDS);
    const uint16_t remaining = NUM_LEDS - led_start;
    led_len = remaining <= 1 ? 1 : static_cast<uint16_t>(1 + random_u16(remaining));
    next_step_ms = now;
  }

  if (active && now >= next_step_ms) {
    if (segment_on) {
      const uint8_t dimmer = flash_index == 0 ? 5 : random_u8(1, 3);
      clear_leds();
      const Color flash_color(255 / dimmer, 255 / dimmer, 255 / dimmer);
      for (uint16_t i = led_start; i < led_start + led_len && i < NUM_LEDS; i++) {
        rt.leds[i] = flash_color;
      }
      segment_on = false;
      next_step_ms = now + random_u8(4, 10);
    } else {
      clear_leds();
      flash_index++;
      if (flash_index >= flashes_remaining) {
        active = false;
        next_strike_ms = now + ((50U + random_u8(static_cast<uint8_t>(clamp_interval(speed, 180, 20)))) * 40U);
      } else {
        segment_on = true;
        next_step_ms = now + (flash_index == 1 ? 130U : (50U + random_u8(100)));
      }
    }
  }

  copy_to_output(it);
}

inline void apply_noise(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  static uint32_t last_palette_refresh = 0;
  auto &rt = state();
  if (initial_run) {
    rt.noise_dist = 0;
    rt.current_palette = {Color(0, 0, 40), Color(0, 80, 120), Color(0, 160, 200), Color(0, 220, 255)};
    rt.target_palette = rt.current_palette;
    clear_leds();
    last_palette_refresh = 0;
  }
  if (!due(last_update, clamp_interval(speed, 90, 10))) {
    copy_to_output(it);
    return;
  }
  if (last_palette_refresh == 0 || (now_ms() - last_palette_refresh) >= 5000) {
    rt.target_palette = std::array<Color, 4>{
        hsv_to_rgb(random_u8(), 255, random_u8(128, 255)),
        hsv_to_rgb(random_u8(), 255, random_u8(128, 255)),
        hsv_to_rgb(random_u8(), 192, random_u8(128, 255)),
        hsv_to_rgb(random_u8(), 255, random_u8(128, 255)),
    };
    last_palette_refresh = now_ms();
  }
  for (size_t i = 0; i < rt.current_palette.size(); i++) {
    rt.current_palette[i] = blend(rt.current_palette[i], rt.target_palette[i], 24);
  }
  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    const auto index = static_cast<uint8_t>(pseudo_noise(i * 30, rt.noise_dist + i * 30) * 255.0f);
    rt.leds[i] = palette_color(rt.current_palette, index);
  }
  rt.noise_dist += 1 + (beatsin8(10, 1, 4) / 64);
  copy_to_output(it);
}

inline void apply_police_all(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  static uint16_t index = 0;
  auto &rt = state();
  if (initial_run) {
    index = 0;
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 80, 10))) {
    copy_to_output(it);
    return;
  }
  const uint16_t top_index = NUM_LEDS / 2;
  const uint16_t other = index >= top_index ? (index + top_index) % NUM_LEDS : index + top_index;
  rt.leds[index] = Color(255, 0, 0);
  rt.leds[other] = Color(0, 0, 255);
  index = (index + 1) % NUM_LEDS;
  copy_to_output(it);
}

inline void apply_police_one(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  static uint16_t index = 0;
  auto &rt = state();
  if (initial_run) {
    index = 0;
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 80, 10))) {
    copy_to_output(it);
    return;
  }
  clear_leds();
  const uint16_t top_index = NUM_LEDS / 2;
  const uint16_t other = index >= top_index ? (index + top_index) % NUM_LEDS : index + top_index;
  rt.leds[index] = Color(255, 0, 0);
  rt.leds[other] = Color(0, 0, 255);
  index = (index + 1) % NUM_LEDS;
  copy_to_output(it);
}

inline void apply_rainbow(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    rt.rainbow_hue = 0;
  }
  if (!due(last_update, clamp_interval(speed, 90, 12))) {
    copy_to_output(it);
    return;
  }
  fill_rainbow(rt.rainbow_hue++, 10);
  copy_to_output(it);
}

inline void apply_rainbow_with_glitter(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    rt.rainbow_hue = 0;
  }
  if (!due(last_update, clamp_interval(speed, 90, 12))) {
    copy_to_output(it);
    return;
  }
  fill_rainbow(rt.rainbow_hue++, 10);
  add_glitter(80, Color(255, 255, 255));
  copy_to_output(it);
}

inline void apply_ripple(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  static int step = -1;
  static uint16_t center = 0;
  static uint8_t colour = 0;
  static uint8_t bgcol = 0;
  auto &rt = state();
  if (initial_run) {
    step = -1;
    center = 0;
    colour = 0;
    bgcol = 0;
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 80, 10))) {
    copy_to_output(it);
    return;
  }
  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    rt.leds[i] = hsv_to_rgb(bgcol++, 255, 15);
  }
  switch (step) {
    case -1:
      center = random_u16(NUM_LEDS);
      colour = random_u8();
      step = 0;
      break;
    case 0:
      rt.leds[center] = hsv_to_rgb(colour, 255, 255);
      step++;
      break;
    case MAX_RIPPLE_STEPS:
      step = -1;
      break;
    default: {
      const auto ripple_color = hsv_to_rgb(colour, 255, static_cast<uint8_t>(255 / step * 2));
      add_inplace(rt.leds[(center + step + NUM_LEDS) % NUM_LEDS], ripple_color);
      add_inplace(rt.leds[(center - step + NUM_LEDS) % NUM_LEDS], ripple_color);
      step++;
      break;
    }
  }
  copy_to_output(it);
}

inline void apply_sinelon(AddressableLight &it, const Color &current_color, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  if (initial_run) {
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 80, 12))) {
    copy_to_output(it);
    return;
  }
  fade_to_black(20);
  const auto pos = beatsin16(13, 0, NUM_LEDS - 1);
  add_inplace(rt.leds[pos], current_color);
  copy_to_output(it);
}

inline void apply_twinkle(AddressableLight &it, float speed, bool initial_run) {
  static uint32_t last_update = 0;
  auto &rt = state();
  const Color light_color(8, 7, 1);
  if (initial_run) {
    clear_leds();
  }
  if (!due(last_update, clamp_interval(speed, 80, 10))) {
    copy_to_output(it);
    return;
  }
  for (auto &led : rt.leds) {
    if (led.r == 0 && led.g == 0 && led.b == 0) {
      continue;
    }
    if (led.r & 1) {
      led.r = led.r > light_color.r ? led.r - light_color.r : 0;
      led.g = led.g > light_color.g ? led.g - light_color.g : 0;
      led.b = led.b > light_color.b ? led.b - light_color.b : 0;
    } else {
      add_inplace(led, light_color);
    }
  }
  if (random_u8() < DENSITY) {
    const auto j = random_u16(NUM_LEDS);
    if (rt.leds[j].r == 0 && rt.leds[j].g == 0 && rt.leds[j].b == 0) {
      rt.leds[j] = light_color;
    }
  }
  copy_to_output(it);
}

}  // namespace tikiroom
