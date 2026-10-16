"""Keep active secrets and Zigbee network inventory out of the public index."""

from pathlib import Path
import json
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
    zone_block = (ROOT / "private_templates/zone.yaml.tmpl").read_text().split("\nzone:\n", 1)[1]
    secrets_example = (ROOT / "travis_secrets.example.yaml").read_text()
    private_examples = json.loads((ROOT / "examples/private_values.example.json").read_text())
    names = re.findall(r"(?m)^  - name: !secret (private_zone_\d{2}_name)$", zone_block)
    coordinates = re.findall(
        r"(?m)^    (?:latitude|longitude): !secret (\S+)$",
        zone_block,
    )
    assert len(names) == 11
    assert len(coordinates) == 22
    for key in names + coordinates:
        if key.startswith("@@PRIVATE:"):
            assert key.endswith("@@")
            key = private_examples[key.removeprefix("@@PRIVATE:").removesuffix("@@")]
        assert re.search(rf"(?m)^{re.escape(key)}:", secrets_example)


def test_inactive_device_addresses_and_appdaemon_backups_are_not_public() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    assert not any(path.startswith("appdaemon.bak/") for path in tracked)
    assert not any("bed_occupancy copy.py" in path for path in tracked)
    assert not any("bed_occupancy.py." in path for path in tracked)
    esphome = (ROOT / "esphome/office-bt-proxy.yaml").read_text()
    assert not re.search(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b", esphome)


def test_network_endpoints_are_loaded_from_private_secrets() -> None:
    paths = (
        "packages/zigbee_zwave.yaml",
        "packages/airplanes.yaml",
        "packages/car.yaml",
        "packages/vacuum_map_guard.yaml",
    )
    examples = (ROOT / "travis_secrets.example.yaml").read_text()
    keys = set()
    for path in paths:
        source = (ROOT / path).read_text()
        assert not re.search(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", source)
        assert not re.search(r"\b[a-zA-Z0-9-]+\.local\b", source)
        keys.update(re.findall(r"!secret (private_[a-z_]+(?:_url|_resource|_origin|_referer|_payload))", source))
    assert len(keys) == 13
    for key in keys:
        assert re.search(rf"(?m)^{re.escape(key)}:", examples)

def test_device_ieee_values_are_private_secrets() -> None:
    examples = (ROOT / "travis_secrets.example.yaml").read_text()
    keys = set()
    for path in ("packages/light.yaml", "packages/workday.yaml", "packages/tv.yaml"):
        source = (ROOT / path).read_text()
        assert not re.search(r"\b(?:[0-9A-Fa-f]{2}:){7}[0-9A-Fa-f]{2}\b", source)
        keys.update(re.findall(r"device_ieee: !secret (private_[a-z0-9_]+_eui)", source))
    assert len(keys) == 1  # only the workday remote still uses a ZHA event
    for key in keys:
        assert re.search(rf"(?m)^{re.escape(key)}:", examples)
    parasoll = (ROOT / "packages/parasoll_fix.yaml").read_text()
    assert 'example: "0x0000000000000001"' in parasoll


def test_birdweather_station_and_domain_alert_text_are_private() -> None:
    birds = (ROOT / "packages/birds.yaml").read_text()
    domain = (ROOT / "packages/domain_name.yaml").read_text()
    examples = (ROOT / "travis_secrets.example.yaml").read_text()

    assert "resource: !secret private_birdweather_species_url" in birds
    assert "resource: !secret private_birdweather_detections_url" in birds
    assert "app.birdweather.com/api/v1/stations/" not in birds
    assert domain.count("message: !secret private_domain_expiry_message") == 2
    for key in (
        "private_birdweather_species_url",
        "private_birdweather_detections_url",
        "private_domain_expiry_message",
    ):
        assert re.search(rf"(?m)^{key}:", examples)


def test_watermeter_endpoints_are_private() -> None:
    source = (ROOT / "packages/utilities.yaml").read_text()
    examples = (ROOT / "travis_secrets.example.yaml").read_text()

    for key in (
        "private_watermeter_light_on_url",
        "private_watermeter_light_off_url",
        "private_watermeter_flow_start_url",
    ):
        assert f"url: !secret {key}" in source
        assert re.search(rf"(?m)^{key}:", examples)
    assert "watermeter.iot." not in source
