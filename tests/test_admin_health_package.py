from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "packages" / "admin_health.yaml"
CONFIGURATION_PATH = ROOT / "configuration.yaml"
DASHBOARD_PATH = ROOT / "lovelace" / "admin_health.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _automation_block(path: Path, automation_id: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r} in {path.name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_admin_health_package_exposes_required_runtime_sources() -> None:
    text = _read(PACKAGE_PATH)

    for token in (
        "unique_id: admin_health_issue_count",
        "unique_id: admin_unavailable_entities",
        "unique_id: admin_stale_entities",
        "unique_id: admin_updates_pending",
        "unique_id: admin_backup_status",
        "sensor.battery_low_20",
        "sensor.battery_dead",
        "sensor.z2m_lifecycle_issues",
        "event.backup_automatic_backup",
        "sensor.backup_next_scheduled_automatic_backup",
        "states.update",
    ):
        assert token in text


def test_admin_health_digest_runs_once_daily_with_stable_notification_tag() -> None:
    block = _automation_block(PACKAGE_PATH, "send_admin_health_daily_digest")

    assert 'at: "07:30:00"' in block
    assert "notification_id: admin-health-digest" in block
    assert "tag: admin-health-digest" in block
    assert "action: notify.all" in block
    assert "continue_on_error: true" in block
    assert "Admin health clear" in block
    assert "Admin health needs attention" in block


def test_admin_health_dashboard_is_registered_as_yaml_dashboard() -> None:
    text = _read(CONFIGURATION_PATH)
    dashboard_block = text.split("dashboards:\n", 1)[1].split("\nsystem_health:", 1)[0]

    assert "admin-health:" in dashboard_block
    assert "mode: yaml" in dashboard_block
    assert "title: Admin Health" in dashboard_block
    assert "show_in_sidebar: true" in dashboard_block
    assert "filename: lovelace/admin_health.yaml" in dashboard_block


def test_admin_health_dashboard_surfaces_runtime_cards() -> None:
    text = _read(DASHBOARD_PATH)

    for token in (
        "type: sections",
        "sensor.admin_health_issue_count",
        "sensor.admin_unavailable_entities",
        "sensor.admin_stale_entities",
        "sensor.admin_updates_pending",
        "sensor.admin_backup_status",
        "sensor.battery_low_20",
        "sensor.battery_low_10",
        "sensor.battery_dead",
        "binary_sensor.z2m_devices_offline",
        "sensor.z2m_lifecycle_issues",
        "automation.send_admin_health_daily_digest",
    ):
        assert token in text

