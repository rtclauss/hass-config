from pathlib import Path


AUTOMATIONS_PATH = Path(__file__).resolve().parents[1] / "automations.yaml"


def test_root_automations_yaml_stays_as_empty_placeholder() -> None:
    lines = [line.rstrip() for line in AUTOMATIONS_PATH.read_text(encoding="utf-8").splitlines()]

    assert lines[0] == "# Intentionally kept empty."
    assert lines[1] == (
        "# This repo stores automations inside domain packages so behavior stays grouped "
        "with the entities and helpers it depends on."
    )
    assert lines[-1] == "[]"
    assert not any(line.lstrip().startswith("- id:") for line in lines)
