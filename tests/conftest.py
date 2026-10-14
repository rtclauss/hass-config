from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEDIA_PLAYER_PATH = ROOT / "packages" / "media_player.yaml"


def pytest_sessionstart(session: pytest.Session) -> None:
    """Materialize synthetic ignored YAML before test modules import it."""
    if MEDIA_PLAYER_PATH.is_file():
        return
    sys.path.insert(0, str(ROOT))
    from scripts.render_private_config import render_all

    render_all(
        ROOT,
        ROOT / "docs/private_config_manifest.json",
        ROOT / "examples/private_values.example.json",
    )


@pytest.fixture
def media_player_config_text() -> str:
    return MEDIA_PLAYER_PATH.read_text(encoding="utf-8")
