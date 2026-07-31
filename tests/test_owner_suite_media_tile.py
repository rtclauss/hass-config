from pathlib import Path


OWNER_SUITE_TILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "lovelace"
    / "tiles"
    / "tiles_master_bedroom.yaml"
)


def test_owner_suite_reset_volume_uses_calibrated_ten_percent_level() -> None:
    text = OWNER_SUITE_TILE_PATH.read_text(encoding="utf-8")
    reset_volume = text.split("name: Reset Volume", 1)[1].split("- type: button", 1)[0]

    assert "volume_level: 0.10" in reset_volume
    assert "media_player.ma_bedroom" in reset_volume
    assert "volume_level: 0.01" not in reset_volume
