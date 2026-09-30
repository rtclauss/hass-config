from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess

STATE_FILENAME = "capture_failure_streak.json"

LOG = logging.getLogger(__name__)


def load_failure_streak(state_dir: Path) -> int:
    path = state_dir / STATE_FILENAME
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    try:
        return max(0, int(data.get("consecutive_failures", 0)))
    except (TypeError, ValueError):
        return 0


def _save_failure_streak(state_dir: Path, streak: int) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / STATE_FILENAME
    path.write_text(json.dumps({"consecutive_failures": streak}), encoding="utf-8")


def record_capture_failure(state_dir: Path) -> int:
    """Increment and persist the consecutive-capture-failure streak, returning the new count."""
    streak = load_failure_streak(state_dir) + 1
    _save_failure_streak(state_dir, streak)
    return streak


def record_capture_success(state_dir: Path) -> None:
    """Reset the streak: a successful capture proves the camera itself is healthy again."""
    _save_failure_streak(state_dir, 0)


def should_reboot(streak: int, *, threshold: int) -> bool:
    return streak >= threshold


def trigger_reboot() -> None:
    """Reboot the host. Only called after should_reboot() confirms the streak threshold.

    The reader service runs as root (no User= in the systemd unit), so this
    needs no sudo. subprocess.run just issues the request; the actual
    shutdown happens asynchronously afterward, so the caller returns normally.
    """
    LOG.error("Rebooting to clear a wedged camera/USB state")
    subprocess.run(["reboot"], check=False)
