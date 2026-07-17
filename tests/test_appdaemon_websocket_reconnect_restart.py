from __future__ import annotations

import importlib.util
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "appdaemon_log_probe.py"
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"

SPEC = importlib.util.spec_from_file_location("appdaemon_log_probe", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _automation_block(automation_id: str) -> str:
    lines = UTILITIES_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line != f"    id: {automation_id}":
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - alias: "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    next_automation = re.compile(r"^  - alias: ")
    for index in range(start + 1, len(lines)):
        if next_automation.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def test_appdaemon_log_probe_reports_recent_websocket_502(tmp_path: Path) -> None:
    now = datetime(2026, 5, 24, 9, 30, 0)
    log_path = tmp_path / "appdaemon_error.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-05-24 09:10:00.000 ERROR HASS: old unrelated error",
                "2026-05-24 09:28:30.000 ERROR HASS: 502, "
                "message='Invalid response status', "
                "url='http://supervisor/core/api/websocket'",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        MODULE.latest_recent_match(log_path, max_age_seconds=600, now=now)
        == "2026-05-24 09:28:30"
    )


def test_appdaemon_log_probe_ignores_stale_or_missing_matches(tmp_path: Path) -> None:
    now = datetime(2026, 5, 24, 9, 30, 0)
    stale_log = tmp_path / "stale_appdaemon_error.log"
    stale_log.write_text(
        "2026-05-24 09:00:00.000 ERROR HASS: Attempting reconnection in 5.0s\n",
        encoding="utf-8",
    )

    assert MODULE.latest_recent_match(stale_log, max_age_seconds=600, now=now) == "clear"
    assert MODULE.latest_recent_match(tmp_path / "missing.log", now=now) == "clear"


def test_utilities_defines_appdaemon_websocket_error_sensor() -> None:
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    assert "command_line:" in text
    assert "unique_id: appdaemon_hass_websocket_reconnect_error" in text
    assert "python3 /config/scripts/appdaemon_log_probe.py" in text
    assert "--log /config/logs/appdaemon_error.log" in text
    assert "--max-age-seconds 600" in text
    assert "scan_interval: 60" in text


def test_existing_appdaemon_restart_automation_handles_websocket_errors() -> None:
    block = _automation_block("restart_appdaemon_on_ha_startup")

    assert "trigger: homeassistant" in block
    assert "id: ha_start" in block
    assert "trigger: state" in block
    assert "entity_id: sensor.appdaemon_hass_websocket_reconnect_error" in block
    assert "id: appdaemon_hass_websocket_reconnect_error" in block
    assert "last_triggered" in block
    assert "total_seconds() > 600" in block
    assert "addon: a0d7b954_appdaemon" in block
    assert block.count("action: hassio.addon_restart") == 1
