"""Keep active secrets and Zigbee network inventory out of the public index."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_zigbee_and_ci_secrets_are_not_tracked() -> None:
    tracked = set(
        subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    )

    assert "travis_secrets.yaml" not in tracked
    assert "zigbee2mqtt/secret.yaml" not in tracked
    assert "zigbee2mqtt/configuration.yaml" not in tracked
    assert not any(
        path.startswith("zigbee2mqtt/configuration_backup") for path in tracked
    )
    assert "travis_secrets.example.yaml" in tracked
    assert "zigbee2mqtt/configuration.example.yaml" in tracked


def test_zigbee_example_uses_private_secret_file() -> None:
    example = (ROOT / "zigbee2mqtt/configuration.example.yaml").read_text()
    assert "'!secret.yaml mqtt_password'" in example
    assert "'!secret.yaml network_key'" in example
    assert "devices:" not in example
