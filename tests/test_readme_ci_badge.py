from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"


def test_readme_uses_relative_public_source_links() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    for path in (
        "private_templates/ui-guest.yaml.tmpl",
        "private_templates/water_softener.yaml.tmpl",
        "private_templates/workday.yaml.tmpl",
        "esphome/bluetoothproxy1.yaml",
        "appdaemon/apps/thermostat_stats.py",
    ):
        assert f"]({path})" in readme
        assert (ROOT / path).is_file()
    assert not re.search(r"https://github\.com/[^/]+/hass-config/", readme)
    assert "travis-ci" not in readme.lower()
