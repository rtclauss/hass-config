from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _automation_block(alias: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line == f"  - alias: {alias}":
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find automation alias {alias!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - alias: "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_hall_garage_laundry_switch_double_taps_control_garage_door() -> None:
    block = _automation_block("hall_garage_laundry_switch_actions")

    assert "id: hall_garage_laundry_switch_actions" in block
    assert block.count("entity_id: sensor.hall_garage_laundry_switch_action") == 2
    assert 'to: "up_double"' in block
    assert 'to: "down_double"' in block
    assert "id: up-double" in block
    assert "id: down-double" in block
    assert "- action: cover.open_cover" in block
    assert "- action: cover.close_cover" in block
    assert "entity_id: cover.garage_door" in block
