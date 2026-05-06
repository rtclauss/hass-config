from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
Z2M_LIFECYCLE_PATH = ROOT / "packages" / "z2m_lifecycle.yaml"
UTILITIES_PATH = ROOT / "packages" / "utilities.yaml"
YAML_SEARCH_ROOTS = (
    ROOT / "automations.yaml",
    ROOT / "scripts.yaml",
    ROOT / "packages",
)


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


def _yaml_paths() -> list[Path]:
    paths: list[Path] = []
    for search_root in YAML_SEARCH_ROOTS:
        if search_root.is_file():
            paths.append(search_root)
            continue
        paths.extend(search_root.rglob("*.yaml"))
    return sorted(paths)


def _has_simple_update_state_availability_condition(text: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "condition: state" not in line:
            continue

        condition_indent = len(line) - len(line.lstrip())
        block_lines = [line]
        for following_line in lines[index + 1 :]:
            stripped = following_line.strip()
            following_indent = len(following_line) - len(following_line.lstrip())
            if stripped and following_indent <= condition_indent:
                break
            block_lines.append(following_line)

        block = "\n".join(block_lines)
        if re.search(r"\bentity_id:\s*update\.", block) and re.search(
            r"\bstate:\s*[\"']?(?:on|off)[\"']?\s*$",
            block,
            re.MULTILINE,
        ):
            return True

    return False


def test_update_state_availability_scanner_only_flags_on_off_checks() -> None:
    assert _has_simple_update_state_availability_condition(
        """
automation:
  - condition: state
    entity_id: update.zigbee_firmware
    state: "on"
"""
    )
    assert not _has_simple_update_state_availability_condition(
        """
automation:
  - condition: state
    entity_id: update.zigbee_firmware
    state: installing
"""
    )


def test_simple_update_availability_checks_use_native_update_conditions() -> None:
    simple_template_condition = re.compile(
        r"condition:\s*template\s*\n(?:[^\n]*\n){0,8}?\s*value_template:\s*(?:>-\s*\n)?"
        r"(?:[^\n]*\n){0,8}?.*(?:is_state\(['\"]update\.|states\(['\"]update\.).*['\"](?:on|off)['\"]",
        re.MULTILINE,
    )
    offenders: list[str] = []

    for path in _yaml_paths():
        text = path.read_text(encoding="utf-8")
        if (
            _has_simple_update_state_availability_condition(text)
            or simple_template_condition.search(text)
        ):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], (
        "Simple update availability decisions should use Home Assistant 2026.5 "
        "`condition: update.is_available` or `condition: update.is_not_available`, "
        f"not state/template conditions: {offenders}"
    )
