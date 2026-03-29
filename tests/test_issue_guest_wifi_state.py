from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUEST_PATH = ROOT / "packages" / "guest.yaml"


def test_guest_wifi_templates_emit_boolean_and_short_count() -> None:
    text = GUEST_PATH.read_text(encoding="utf-8")

    assert "unique_id: guest_on_wifi" in text
    assert "{{ is_number(state) and state | float >= 1 }}" in text
    assert "unique_id: guests_on_wifi" in text
    assert (
        "{{ states.device_tracker | selectattr('state', 'eq', 'home') | "
        "selectattr('attributes.is_guest', 'eq', true) | list | count }}"
    ) in text
