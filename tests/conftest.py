from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def media_player_config_text() -> str:
    return (Path(__file__).resolve().parents[1] / "packages" / "media_player.yaml").read_text(
        encoding="utf-8"
    )
