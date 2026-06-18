from __future__ import annotations

import re
from pathlib import Path


WORKDAY_PATH = Path(__file__).resolve().parents[1] / "packages" / "workday.yaml"


def _script_block(script_id: str) -> str:
    lines = WORKDAY_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def test_mpr_news_wrapper_falls_back_to_direct_publicradio_stream() -> None:
    block = _script_block("sonos_mpr_news_wake_up")

    # Primary stays the TuneIn station; the fallback is the direct MPR News
    # Icecast MP3, which reaches publicradio.org without the opml.radiotime.com
    # resolver that failed on 2026-06-18.
    assert "tunein--S3NwgspV://radio/s34350" in block
    assert "fallback_uri:" in block
    assert "https://nis.stream.publicradio.org/nis.mp3" in block


def test_the_current_wrapper_falls_back_to_direct_publicradio_stream() -> None:
    block = _script_block("sonos_the_current_wake_up")

    assert "fallback_uri:" in block
    assert "https://current.stream.publicradio.org/current.mp3" in block
