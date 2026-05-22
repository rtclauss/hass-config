from __future__ import annotations

from pathlib import Path


LIGHT_PATH = Path(__file__).resolve().parents[1] / "packages" / "light.yaml"


def _automation_block(automation_id: str) -> str:
    lines = LIGHT_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line != f"  - id: {automation_id}":
            continue
        start = index
        break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_under_bed_zone_motion_does_not_turn_strip_off_before_zone_update() -> None:
    block = _automation_block("toggle_on_under_bed_on_motion")
    actions = block.split("    action:", 1)[1]
    zone_section = actions.split("id: zone_1_on", 1)[1].split("id: motion_on", 1)[0]

    assert "action: light.turn_off" not in zone_section
    assert "entity_id: light.bed_lightstrip" in zone_section
    assert zone_section.count("action: adaptive_lighting.apply") == 4
    assert zone_section.count("action: lifx.set_state") == 4


def test_under_bed_zone_lifx_calls_only_use_supported_zone_fields() -> None:
    block = _automation_block("toggle_on_under_bed_on_motion")
    actions = block.split("    action:", 1)[1]
    zone_section = actions.split("id: zone_1_on", 1)[1].split("id: motion_on", 1)[0]

    assert "brightness_pct:" not in zone_section
    assert "kelvin:" not in zone_section
    assert "power: true" in zone_section
    assert "zones: [0, 1]" in zone_section
    assert "zones: [2, 3]" in zone_section
    assert "zones: [4, 5]" in zone_section
    assert "zones: [6, 7]" in zone_section
