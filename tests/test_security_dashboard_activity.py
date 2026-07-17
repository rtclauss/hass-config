from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIGURATION_PATH = ROOT / "configuration.yaml"
CAMERA_PACKAGE_PATH = ROOT / "packages" / "camera.yaml"
ALERTS_PACKAGE_PATH = ROOT / "packages" / "alerts.yaml"
DOC_PATH = ROOT / "docs" / "security_dashboard.md"
README_PATH = ROOT / "README.md"


def _customize_block(text: str, entity_id: str) -> str:
    lines = text.splitlines()
    needle = f"    {entity_id}:"

    try:
        start = lines.index(needle)
    except ValueError as exc:
        raise AssertionError(f"Missing customize block for {entity_id}") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("    ") and not lines[index].startswith("      "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_security_activity_dependencies_and_privacy_filter_are_preserved() -> None:
    text = CONFIGURATION_PATH.read_text(encoding="utf-8")
    recorder_block = text.split("recorder:\n", 1)[1].split("\ninfluxdb:", 1)[0]
    excluded_domains = {
        line.removeprefix("      - ").strip()
        for line in recorder_block.splitlines()
        if line.startswith("      - ")
    }

    assert "logbook:\n" in text
    assert "camera" in excluded_domains
    assert {
        "alarm_control_panel",
        "lock",
        "cover",
        "binary_sensor",
        "person",
    }.isdisjoint(excluded_domains)


def test_physical_camera_motion_entities_use_motion_device_class() -> None:
    text = CAMERA_PACKAGE_PATH.read_text(encoding="utf-8")

    for entity_id in (
        "binary_sensor.livingroom_motion_sensor",
        "binary_sensor.tikiroomcam_motionsensor",
    ):
        block = _customize_block(text, entity_id)
        assert "device_class: motion" in block


def test_camera_snapshot_notifications_use_the_classified_motion_entities() -> None:
    text = ALERTS_PACKAGE_PATH.read_text(encoding="utf-8")
    block = text.split("  - alias: send_pic_from_camera", 1)[1].split(
        "  - alias: arm_alarm", 1
    )[0]

    assert "binary_sensor.livingroom_motion_sensor" in block
    assert "binary_sensor.tikiroomcam_motionsensor" in block


def test_security_dashboard_runtime_contract_is_discoverable() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "docs/security_dashboard.md" in readme
    assert "Keep the `camera` domain excluded from Recorder" in doc
    assert "Home Assistant 2026.7.2" in doc
    assert "device-registry API to Dining room" in doc
