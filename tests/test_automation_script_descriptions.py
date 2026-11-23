"""Every automation and script must document its intent, and the catalog must be current."""

from __future__ import annotations

from scripts.generate_automation_catalog import CATALOG, collect, render_catalog


def test_every_automation_and_script_has_a_description() -> None:
    missing = [
        f"{path}: {item.kind} {item.key or item.alias}"
        for path, items in collect().items()
        for item in items
        if not item.description
    ]
    assert not missing, "Add a description: field to:\n" + "\n".join(missing)


def test_catalog_is_current() -> None:
    expected = render_catalog(collect())
    actual = CATALOG.read_text(encoding="utf-8") if CATALOG.is_file() else ""
    assert actual == expected, (
        "docs/automations_and_scripts.md is stale; run "
        "`uv run python scripts/generate_automation_catalog.py`"
    )
