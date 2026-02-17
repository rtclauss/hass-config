#!/usr/bin/env python3
"""Validate local pinned Python version against the latest Home Assistant release."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PYPI_HOMEASSISTANT_JSON = "https://pypi.org/pypi/homeassistant/json"
VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){0,2}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether the repository's pinned Python version is supported by "
            "the latest official Home Assistant release."
        )
    )
    parser.add_argument(
        "--python-version-file",
        default=".python-version",
        help="Path to the file containing the pinned Python version (default: .python-version).",
    )
    return parser.parse_args()


def parse_version(version: str) -> tuple[int, int, int]:
    raw = version.strip()
    if not VERSION_PATTERN.match(raw):
        raise SystemExit(
            f"Unsupported version format '{version}'. Expected numeric dot-separated version."
        )
    parts = [int(piece) for piece in raw.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def read_pinned_version(path: Path) -> tuple[int, int, int]:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing {path}. Add a pinned Python version first.") from exc

    if not content:
        raise SystemExit(f"{path} is empty. Add a pinned Python version.")

    return parse_version(content)


def fetch_latest_homeassistant_metadata() -> tuple[str, str]:
    try:
        with urllib.request.urlopen(PYPI_HOMEASSISTANT_JSON, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read {PYPI_HOMEASSISTANT_JSON}: {exc}") from exc

    info = payload.get("info", {})
    version = info.get("version")
    requires_python = info.get("requires_python")

    if not version or not requires_python:
        raise SystemExit(
            "PyPI metadata is missing version/requires_python for homeassistant."
        )

    return version, requires_python


def version_is_supported(version: tuple[int, int, int], spec: str) -> bool:
    specifiers = [entry.strip() for entry in spec.split(",") if entry.strip()]

    for entry in specifiers:
        operator = None
        for candidate in ("~=", ">=", "<=", "==", "!=", ">", "<"):
            if entry.startswith(candidate):
                operator = candidate
                break

        if operator is None:
            raise SystemExit(f"Unsupported specifier '{entry}' in requires_python='{spec}'.")

        target_text = entry[len(operator) :].strip()
        target = parse_version(target_text)

        if operator == ">=" and not (version >= target):
            return False
        if operator == ">" and not (version > target):
            return False
        if operator == "<=" and not (version <= target):
            return False
        if operator == "<" and not (version < target):
            return False
        if operator == "==" and not (version == target):
            return False
        if operator == "!=" and not (version != target):
            return False
        if operator == "~=":
            # Compatible release: >=target and <next minor for three-part versions.
            upper = (target[0], target[1] + 1, 0)
            if not (version >= target and version < upper):
                return False

    return True


def main() -> int:
    args = parse_args()
    version_file = Path(args.python_version_file)

    pinned_python = read_pinned_version(version_file)
    ha_version, ha_requires_python = fetch_latest_homeassistant_metadata()
    supported = version_is_supported(pinned_python, ha_requires_python)

    print(f"Pinned Python: {pinned_python[0]}.{pinned_python[1]}.{pinned_python[2]}")
    print(f"Latest Home Assistant: {ha_version}")
    print(f"Latest Home Assistant requires: {ha_requires_python}")

    if not supported:
        print(
            "Pinned Python does not satisfy the latest Home Assistant requirement.",
            file=sys.stderr,
        )
        return 1

    print("Pinned Python satisfies the latest Home Assistant requirement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
