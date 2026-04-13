from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "specs" / "z2m_lifecycle.allium"
PACKAGE_PATH = ROOT / "packages" / "z2m_lifecycle.yaml"


def test_z2m_lifecycle_spec_covers_repo_contract() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "rule DetectJoinThenDropFromLeave",
        "rule DetectJoinThenDropFromRosterLoss",
        "rule DetectLeftNetwork",
        "rule RecordDeviceInterviewFailure",
        "rule RequestDeviceDecommission",
        "rule ConfirmNormalDeviceDecommission",
        "rule ConfirmForceDeviceDecommission",
        "single_device_churn_never_triggers_host_restart",
        "InventoryMarkdownUpdateRequired(device, configured_to_spare_stock)",
    ):
        assert token in text


def test_z2m_lifecycle_package_matches_allium_edge_cases() -> None:
    text = PACKAGE_PATH.read_text(encoding="utf-8")

    for token in (
        "joined and immediately left the network",
        "joined or announced but never stabilized",
        "left the network",
        "device interview failed",
        "topic: zigbee2mqtt/bridge/request/device/remove",
        "topic: zigbee2mqtt/bridge/response/device/remove",
        "topic: zigbee2mqtt/bridge/response/coordinator_check",
    ):
        assert token in text
