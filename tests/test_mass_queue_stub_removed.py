from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MASS_QUEUE_SERVICES_PATH = REPO_ROOT / "custom_components" / "mass_queue" / "services.yaml"


def test_incomplete_mass_queue_stub_is_not_checked_in() -> None:
    assert not MASS_QUEUE_SERVICES_PATH.exists()
