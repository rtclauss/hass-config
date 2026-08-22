from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "docs" / "infra" / "loki" / "loki-config.yaml"


def test_compactor_sets_delete_request_store_alongside_retention() -> None:
    # Codex P1 on #520: newer Loki releases require compactor.
    # delete_request_store whenever retention_enabled is true and fail
    # startup validation without it, rather than falling back to
    # shared_store. Must stay set as long as retention is enabled.
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    compactor = config["compactor"]

    assert compactor["retention_enabled"] is True
    assert compactor["delete_request_store"] == "filesystem"
