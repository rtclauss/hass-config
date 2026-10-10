from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
AUTOMATIONS_PATH = ROOT / "automations.example.yaml"


def test_public_automations_example_stays_empty() -> None:
    lines = [line.rstrip() for line in AUTOMATIONS_PATH.read_text(encoding="utf-8").splitlines()]

    assert lines[0] == "# Intentionally kept empty."
    assert lines[1] == (
        "# This repo stores automations inside domain packages so behavior stays grouped "
        "with the entities and helpers it depends on."
    )
    assert lines[-1] == "[]"
    assert not any(line.lstrip().startswith("- id:") for line in lines)


def test_live_automations_are_not_tracked() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    assert "automations.yaml" not in tracked
    assert "automations.example.yaml" in tracked
    assert subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "automations.yaml"], cwd=ROOT
    ).returncode == 0
