from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATHS = [
    ROOT / "configuration.yaml",
    ROOT / "automations.yaml",
    ROOT / "scripts.yaml",
    *sorted((ROOT / "packages").glob("*.yaml")),
    *sorted((ROOT / "blueprints").rglob("*.yaml")),
]

CUSTOMIZE_AUTOMATION_RE = re.compile(r"^\s{4}automation\.([A-Za-z0-9_]+):\s*$")
AUTOMATION_ID_RE = re.compile(
    r"^(?:\s{2}-\s+id:\s+|\s{4}id:\s+)([A-Za-z0-9_]+)\s*$"
)


def test_customized_automations_have_matching_definitions() -> None:
    customized_automations: dict[str, list[str]] = {}
    defined_automations: set[str] = set()

    for path in CONFIG_PATHS:
        for line in path.read_text(encoding="utf-8").splitlines():
            customize_match = CUSTOMIZE_AUTOMATION_RE.match(line)
            if customize_match:
                automation_id = customize_match.group(1)
                customized_automations.setdefault(automation_id, []).append(path.name)
                continue

            id_match = AUTOMATION_ID_RE.match(line)
            if id_match:
                defined_automations.add(id_match.group(1))

    missing = {
        automation_id: sorted(paths)
        for automation_id, paths in customized_automations.items()
        if automation_id not in defined_automations
    }

    assert not missing, (
        "Customize entries reference automations with no matching definition: "
        f"{missing}"
    )
