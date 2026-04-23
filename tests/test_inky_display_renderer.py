from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

from inky_display import HEIGHT, WIDTH, payload_hash, render_payload, validate_payload


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "inky_display" / "samples"


def _sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize(
    "name",
    [
        "owner_suite_night_preview.json",
        "owner_suite_morning.json",
        "owner_suite_up_for_day.json",
        "owner_suite_midday.json",
    ],
)
def test_owner_suite_samples_render_as_400_by_300_pngs(name: str) -> None:
    payload = validate_payload(_sample(name))
    rendered = render_payload(payload)

    assert _png_size(rendered) == (WIDTH, HEIGHT)
    assert len(rendered) > 1000


def test_payload_hash_is_stable_for_duplicate_suppression() -> None:
    payload = validate_payload(_sample("owner_suite_night_preview.json"))

    assert payload_hash(payload) == payload_hash(validate_payload(_sample("owner_suite_night_preview.json")))


def test_payload_validation_limits_rows_for_legibility() -> None:
    data = _sample("owner_suite_night_preview.json")
    data["sections"][0]["rows"].append({"label": "Extra", "value": "Hidden", "level": "urgent"})

    payload = validate_payload(data)

    assert len(payload.sections[0]["rows"]) == 4


def test_payload_validation_rejects_wrong_mode_for_display() -> None:
    data = _sample("owner_suite_night_preview.json")
    data["mode"] = "guest_info"

    with pytest.raises(ValueError, match="Unsupported mode"):
        validate_payload(data)


def test_payload_validation_skips_unknown_sections() -> None:
    data = _sample("owner_suite_night_preview.json")
    data["sections"].append({"type": "qr", "value": "later"})

    payload = validate_payload(data)

    assert len(payload.sections) == 1

