from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"


def test_readme_build_badge_targets_live_validation_workflow() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert (
        "https://github.com/rtclauss/hass-config/actions/workflows/"
        "validate-config.yml/badge.svg?branch=main"
    ) in readme
    assert (
        "https://github.com/rtclauss/hass-config/actions/workflows/"
        "validate-config.yml?query=branch%3Amain"
    ) in readme
    assert "travis-ci" not in readme.lower()
