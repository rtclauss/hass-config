from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_GLOBS = ("*.yaml", "packages/*.yaml")
MAX_INPUT_TEXT_STATE_LENGTH = 255


def _input_text_maxima(path: Path) -> list[tuple[str, int]]:
    helpers: list[tuple[str, int]] = []
    current_helper: str | None = None
    in_input_text_block = False

    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^[A-Za-z0-9_]+:\s*$", line):
            in_input_text_block = line == "input_text:"
            current_helper = None
            continue

        if not in_input_text_block:
            continue

        helper_match = re.match(r"^  ([A-Za-z0-9_]+):\s*$", line)
        if helper_match:
            current_helper = helper_match.group(1)
            continue

        max_match = re.match(r"^    max:\s+(\d+)\s*$", line)
        if max_match and current_helper is not None:
            helpers.append((current_helper, int(max_match.group(1))))

    return helpers


def test_yaml_defined_input_text_helpers_stay_within_home_assistant_state_limit() -> None:
    offenders: list[str] = []

    for pattern in PACKAGE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            for helper, max_length in _input_text_maxima(path):
                if max_length > MAX_INPUT_TEXT_STATE_LENGTH:
                    offenders.append(f"{path.relative_to(ROOT)}:{helper}={max_length}")

    assert offenders == []


def test_window_open_exclusions_helper_uses_the_supported_limit_boundary() -> None:
    climate_maxima = dict(_input_text_maxima(ROOT / "packages" / "climate.yaml"))

    assert climate_maxima["any_window_open_exclude_entities"] == MAX_INPUT_TEXT_STATE_LENGTH
