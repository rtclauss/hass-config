from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKDAY_PATH = ROOT / "packages" / "workday.yaml"


def _script_block(path: Path, script_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and lines[index].endswith(":") and not lines[index].startswith("    "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_wake_up_script_uses_supported_color_temperature_fields_and_keeps_running() -> None:
    block = _script_block(WORKDAY_PATH, "wake_up_script")

    assert "cover.owner_suite_blinds_ha" in block
    assert "color_temp_kelvin: 2700" in block
    assert "color_temp_kelvin: 6500" in block
    assert "\n          kelvin:" not in block
    assert block.count("continue_on_error: true") >= 3
