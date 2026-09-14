from __future__ import annotations

import re
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[1] / "docs" / "infra" / "loki" / "loki-config.yaml"


def test_compactor_sets_delete_request_store_alongside_retention() -> None:
    # Codex P1 on #520: newer Loki releases require compactor.
    # delete_request_store whenever retention_enabled is true and fail
    # startup validation without it, rather than falling back to
    # shared_store. Must stay set as long as retention is enabled.
    config = CONFIG_PATH.read_text(encoding="utf-8")
    compactor_match = re.search(
        r"^compactor:\n(?P<body>(?:  [^\n]*(?:\n|$))*)",
        config,
        re.MULTILINE,
    )

    assert compactor_match is not None
    compactor = compactor_match.group("body")
    assert re.search(r"^  retention_enabled:\s*true\s*$", compactor, re.MULTILINE)
    assert re.search(
        r"^  delete_request_store:\s*filesystem\s*$",
        compactor,
        re.MULTILINE,
    )
