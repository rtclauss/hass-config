"""Check private Zigbee2MQTT inventory against public HA availability sensors.

Pass the live configuration on stdin to avoid copying it into the repository.
Only counts are printed; device names and IEEE addresses stay private.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


def named_devices(configuration: str) -> set[str]:
    match = re.search(r"^devices:\n(?P<body>.*?)(?=^groups:|\Z)", configuration, re.M | re.S)
    if match is None:
        return set()
    names = re.findall(r"^\s+friendly_name:\s+(.+)$", match.group("body"), re.M)
    cleaned = {name.strip().strip("'\"") for name in names}
    return {name for name in cleaned if not name.startswith("0x")}


def availability_devices(package: str) -> set[str]:
    topics = re.findall(r'^\s+state_topic: "zigbee2mqtt/(.+)/availability"$', package, re.M)
    return set(topics)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", help="Live Zigbee2MQTT YAML path, or - for stdin")
    parser.add_argument(
        "--package", type=Path, default=ROOT / "packages" / "z2m_availability.yaml"
    )
    args = parser.parse_args()

    configuration = (
        sys.stdin.read() if args.configuration == "-" else Path(args.configuration).read_text()
    )
    devices = named_devices(configuration)
    sensors = availability_devices(args.package.read_text())
    missing = devices - sensors
    print(f"Named devices: {len(devices)}; availability sensors: {len(sensors)}; missing: {len(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
