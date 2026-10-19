from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_esphome_credentials_and_identity_use_ignored_secrets() -> None:
    references = {
        "esphome/bluetoothproxy1.yaml": "ota_password: !secret bluetoothproxy1_ota_password",
        "esphome/livingroombtproxy.yaml": "ota_password: !secret livingroombtproxy_ota_password",
        "esphome/office-bt-proxy.yaml": "ota_password: !secret office_bt_proxy_ota_password",
        "esphome/packages/common/base.yaml": "fallback_ap_password: !secret bluetooth_proxy_fallback_ap_password",
        "esphome/tikiroom.yaml": "password: !secret tikiroom_fallback_ap_password",
    }
    for path, reference in references.items():
        assert reference in (ROOT / path).read_text()

    base = (ROOT / "esphome/packages/common/base.yaml").read_text()
    office = (ROOT / "esphome/office-bt-proxy.yaml").read_text()
    assert "project_name: !secret bluetooth_proxy_project_name" in base
    assert "yourname: !secret resident_display_name" in office

    example = (ROOT / "examples/esphome_secrets.example.yaml").read_text()
    for key in (
        "bluetoothproxy1_ota_password",
        "livingroombtproxy_ota_password",
        "office_bt_proxy_ota_password",
        "bluetooth_proxy_fallback_ap_password",
        "tikiroom_fallback_ap_password",
        "bluetooth_proxy_project_name",
        "resident_display_name",
    ):
        assert re.search(rf"(?m)^{key}: \"?example", example, re.I)


def test_ci_prepares_package_secrets_from_synthetic_example() -> None:
    workflow = (ROOT / ".github/workflows/validate-config.yml").read_text()
    assert "cp examples/esphome_secrets.example.yaml esphome/secrets.yaml" in workflow
    assert 'config_dir.rglob("*.yaml")' in workflow
