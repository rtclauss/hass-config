from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def is_ignored(path: str) -> bool:
    """Ask git whether a path would be ignored, ignoring the index (so tracked files count)."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", path],
        capture_output=True,
    )
    return result.returncode == 0


def test_hacs_owned_files_of_every_type_are_ignored() -> None:
    for path in (
        "custom_components/places/__init__.py",
        "custom_components/places/services.yaml",
        "custom_components/places/manifest.json",
        "custom_components/places/translations/en.json",
        "custom_components/brand_new_integration/sensor.py",
        "custom_components/hacs/README.md",
    ):
        assert is_ignored(path), path


def test_only_the_mass_queue_services_stub_is_kept() -> None:
    assert not is_ignored("custom_components/mass_queue/services.yaml")
    for path in (
        "custom_components/mass_queue/extra.yaml",
        "custom_components/mass_queue/manifest.json",
        "custom_components/mass_queue/sub/other.yaml",
        "custom_components/mass_queue/__init__.py",
    ):
        assert is_ignored(path), path
