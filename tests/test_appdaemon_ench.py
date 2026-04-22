from __future__ import annotations

import re
from pathlib import Path


APPDAEMON_APPS_PATH = Path(__file__).resolve().parents[1] / "appdaemon" / "apps" / "apps.yaml"


def _top_level_block(config: str, key: str) -> str:
    match = re.search(
        rf"^{re.escape(key)}:\n(.*?)(?=^[A-Za-z0-9_]+:|\Z)",
        config,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(0) if match else ""


def test_ench_battery_notifications_remain_disabled() -> None:
    config = APPDAEMON_APPS_PATH.read_text(encoding="utf-8")
    ench_block = _top_level_block(config, "ench")

    assert "\n  battery:" not in ench_block
