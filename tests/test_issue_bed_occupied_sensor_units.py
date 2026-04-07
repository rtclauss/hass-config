from __future__ import annotations

from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def test_bed_occupied_numeric_sensors_do_not_use_invalid_power_factor_metadata() -> None:
    text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    east_block = text.split('name: "east_bed_occupied_num"', maxsplit=1)[1].split(
        'name: "west_bed_occupied_num"',
        maxsplit=1,
    )[0]
    west_block = text.split('name: "west_bed_occupied_num"', maxsplit=1)[1].split(
        "\n\n",
        maxsplit=1,
    )[0]

    for block in (east_block, west_block):
        assert 'state_class: measurement' in block
        assert 'device_class: power_factor' not in block
        assert 'unit_of_measurement: "1"' not in block
