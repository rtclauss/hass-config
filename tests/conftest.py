from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEDIA_PLAYER_PATH = ROOT / "packages" / "media_player.yaml"

# The Smart Cat integration tests need Home Assistant's test harness, which
# also disables sockets and changes the event loop for every test. They run in
# their own CI job (pytest tests/smartcat_ha); skip them in the normal suite.
try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:
    collect_ignore = ["smartcat_ha"]


def pytest_sessionstart(session: pytest.Session) -> None:
    """Materialize synthetic ignored YAML before test modules import it."""
    sys.path.insert(0, str(ROOT))
    from scripts.render_private_config import render_all

    render_all(
        ROOT,
        ROOT / "docs/private_config_manifest.json",
        ROOT / "examples/private_values.example.json",
        missing_only=True,
    )


@pytest.fixture
def media_player_config_text() -> str:
    return MEDIA_PLAYER_PATH.read_text(encoding="utf-8")
