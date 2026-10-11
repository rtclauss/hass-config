"""Keep active secrets and Zigbee network inventory out of the public index."""

from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_z2m_availability_roster import (  # noqa: E402
    availability_devices,
    named_devices,
)


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_zigbee_and_ci_secrets_are_not_tracked() -> None:
    tracked = set(
        subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    )

    assert "travis_secrets.yaml" not in tracked
    assert "zigbee2mqtt/secret.yaml" not in tracked
    assert "zigbee2mqtt/configuration.yaml" not in tracked
    assert "packages/z2m_availability.yaml" not in tracked
    assert not any(
        path.startswith("zigbee2mqtt/configuration_backup") for path in tracked
    )
    assert "travis_secrets.example.yaml" in tracked
    assert "zigbee2mqtt/configuration.example.yaml" in tracked
    assert "examples/z2m_availability.yaml" in tracked


def test_private_migration_backup_is_ignored() -> None:
    ignored = subprocess.check_output(
        ["git", "check-ignore", ".private-runtime-backup/zigbee2mqtt/secret.yaml"],
        cwd=ROOT,
        text=True,
    ).strip()
    assert ignored == ".private-runtime-backup/zigbee2mqtt/secret.yaml"


def test_zigbee_example_uses_private_secret_file() -> None:
    example = (ROOT / "zigbee2mqtt/configuration.example.yaml").read_text()
    assert "'!secret.yaml mqtt_password'" in example
    assert "'!secret.yaml network_key'" in example
    assert example.count("friendly_name:") <= 4
    assert "0x0000000000000001" in example


def test_private_roster_checker_accepts_public_example() -> None:
    configuration = (ROOT / "zigbee2mqtt/configuration.example.yaml").read_text()
    package = (ROOT / "examples/z2m_availability.yaml").read_text()
    assert named_devices(configuration) <= availability_devices(package)


def test_private_roster_checker_detects_missing_sensor() -> None:
    configuration = "devices:\n  '0x0000000000000001':\n    friendly_name: Example Device\n"
    assert named_devices(configuration) - availability_devices("") == {"Example Device"}


def test_private_roster_checker_ignores_unnamed_ieee_devices() -> None:
    configuration = (
        "devices:\n"
        "  '0x0000000000000001':\n"
        "    friendly_name: '0x0000000000000001'\n"
    )
    assert named_devices(configuration) == set()


def test_zone_names_and_coordinates_are_private_secrets() -> None:
    zone_block = (ROOT / "packages/zone.yaml").read_text().split("\nzone:\n", 1)[1]
    secrets_example = (ROOT / "travis_secrets.example.yaml").read_text()
    names = re.findall(r"(?m)^  - name: !secret (private_zone_\d{2}_name)$", zone_block)
    coordinates = re.findall(
        r"(?m)^    (?:latitude|longitude): !secret (private_zone_\d{2}_(?:latitude|longitude))$",
        zone_block,
    )
    assert len(names) == 11
    assert len(coordinates) == 12
    for key in names + coordinates:
        assert re.search(rf"(?m)^{re.escape(key)}:", secrets_example)
