"""Keep Home Assistant's UI-owned state outside public Git."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ROOT / "tests" / "fixtures" / "dashboard.example.json",
    ROOT / "tests" / "fixtures" / "dashboard_strategy.example.json",
)


def test_ui_storage_is_private_and_public_fixture_is_tracked() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    assert not any(path.startswith(".storage/") for path in tracked)
    assert all(str(path.relative_to(ROOT)) in tracked for path in FIXTURES)
    assert subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", ".storage/lovelace.private"],
        cwd=ROOT,
    ).returncode == 0


def test_dashboard_examples_have_no_personal_markers() -> None:
    for path in FIXTURES:
        text = path.read_text(encoding="utf-8")
        dashboard = json.loads(text)
        assert dashboard["data"]["config"]["views"]
        assert not re.search(r"(?i)ryan|nigori|zeke|tyson|wethop|rtclauss", text)
        assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
        assert not re.search(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", text)
