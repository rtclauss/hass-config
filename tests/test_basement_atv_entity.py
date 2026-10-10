from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_ENTITY = re.compile(r"media_player\.basement(?![A-Za-z0-9_])")
NEW_ENTITY = "media_player.basement_great_room_basement_atv"


def test_basement_apple_tv_references_use_live_entity_id() -> None:
    paths = [*ROOT.joinpath("packages").glob("*.yaml"), *ROOT.joinpath("lovelace").rglob("*.yaml")]
    references = []

    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert not OLD_ENTITY.search(content), f"stale Apple TV entity in {path}"
        if NEW_ENTITY in content:
            references.append(path.relative_to(ROOT).as_posix())

    assert "packages/tv.yaml" in references
    assert "packages/light.yaml" in references
    assert "packages/tiki_time.yaml" in references
    assert "lovelace/tiles/tiles_living_room.yaml" in references
