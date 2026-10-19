from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MASS_QUEUE_SERVICES_PATH = REPO_ROOT / "custom_components" / "mass_queue" / "services.yaml"


def test_mass_queue_services_stub_is_present_for_music_assistant_dashboard() -> None:
    contents = MASS_QUEUE_SERVICES_PATH.read_text(encoding="utf-8")

    for token in (
        "get_queue_items:",
        "play_queue_item:",
        "clear_queue_from_here:",
        "integration: mass_queue",
    ):
        assert token in contents
