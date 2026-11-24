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


def test_smartcat_is_tracked_except_bytecode() -> None:
    # Smart Cat is written for this house, not installed from HACS (#1248).
    for path in (
        "custom_components/smartcat/__init__.py",
        "custom_components/smartcat/manifest.json",
        "custom_components/smartcat/core/identify.py",
        "custom_components/smartcat/translations/en.json",
        "tests/smartcat_ha/test_smartcat_integration.py",
    ):
        assert not is_ignored(path), path
    assert is_ignored("custom_components/smartcat/__pycache__/sensor.cpython-314.pyc")
    assert is_ignored("custom_components/smartcat/core/__pycache__/store.cpython-314.pyc")
