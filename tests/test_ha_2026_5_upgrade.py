from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
Z2M_LIFECYCLE_PATH = ROOT / "packages" / "z2m_lifecycle.yaml"
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"


def test_supervisor_restart_actions_preserve_failure_tolerant_behavior() -> None:
    for package_path in (Z2M_LIFECYCLE_PATH, UTILITIES_PATH):
        lines = package_path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "action: hassio.addon_restart" not in line:
                continue

            action_indent = len(line) - len(line.lstrip())
            following = lines[index + 1 : index + 4]
            expected = f"{' ' * (action_indent + 2)}continue_on_error: true"
            assert expected in following, (
                f"{package_path} must keep hassio.addon_restart failure-tolerant "
                "for Home Assistant 2026.5 supervisor action semantics"
            )
