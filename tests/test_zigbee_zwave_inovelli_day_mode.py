from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _script_block(name: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line == f"  {name}:":
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script {name!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_day_mode_switches_restores_old_single_tap_behavior() -> None:
    block = _script_block("day_mode_switches_general")

    assert "all_day_mode_singletapbehavior_switches" in block
    assert 'option: "Old Behavior"' in block
    assert 'option: "New Behavior"' not in block


def test_day_mode_switches_keeps_full_brightness_defaults() -> None:
    block = _script_block("day_mode_switches_general")

    assert "all_day_mode_defaultlevellocal_switches" in block
    assert "all_day_mode_defaultlevelremote_switches" in block
    assert block.count('value: "254"') >= 2


def test_reset_inovelli_switches_restores_old_single_tap_behavior() -> None:
    block = _script_block("reset_inovelli_switches")

    assert "all_inovelli_switches_singletapbehavior_mode" in block
    assert 'option: "Old Behavior"' in block
