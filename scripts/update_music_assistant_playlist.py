#!/usr/bin/env python3
"""Append Music Assistant items to supported playlist scripts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SUPPORTED_PLAYLIST_SCRIPTS = {
    "bedroom_playlist_0",
    "bedroom_playlist_1",
    "bedroom_playlist_2",
    "bedroom_playlist_3",
    "bedroom_playlist_4",
    "bedroom_playlist_5",
    "spotify_arrival",
    "spotify_bedtime",
    "spotify_wake_up",
}

SCRIPT_START_RE = re.compile(r"^  (?P<script>[A-Za-z0-9_]+):$")


def append_item_to_playlist_config(content: str, script_id: str, item_uri: str) -> tuple[str, bool]:
    """Append an item URI to a supported script's Jinja `plists` list."""
    if script_id not in SUPPORTED_PLAYLIST_SCRIPTS:
        raise ValueError(f"Unsupported playlist target: {script_id}")
    if not item_uri or any(char in item_uri for char in ('"', "\n", "\r")):
        raise ValueError("Playlist items must be non-empty and single-line")

    lines = content.splitlines()
    start_index = _find_script_start(lines, script_id)
    end_index = _find_script_end(lines, start_index)
    plists_start, plists_end = _find_plists_block(lines, start_index, end_index)
    plists_block = "\n".join(lines[plists_start : plists_end + 1])
    if item_uri in re.findall(r'"([^"\n]+)"', plists_block):
        return content, False

    insert_index = plists_end
    last_item_index = _find_last_item_line(lines, plists_start, plists_end)
    if last_item_index is None:
        raise ValueError(f"Could not find any playlist items for {script_id}")

    if lines[last_item_index].rstrip().endswith('"'):
        lines[last_item_index] = f"{lines[last_item_index]},"

    closing_indent = lines[plists_end][: len(lines[plists_end]) - len(lines[plists_end].lstrip(" "))]
    lines.insert(insert_index, f'{closing_indent}"{item_uri}"')
    updated = "\n".join(lines)
    if content.endswith("\n"):
        updated += "\n"
    return updated, True


def _find_script_start(lines: list[str], script_id: str) -> int:
    needle = f"  {script_id}:"
    for index, line in enumerate(lines):
        if line == needle:
            return index
    raise ValueError(f"Could not find script {script_id}")


def _find_script_end(lines: list[str], start_index: int) -> int:
    for index in range(start_index + 1, len(lines)):
        if SCRIPT_START_RE.match(lines[index]):
            return index
    return len(lines)


def _find_plists_block(lines: list[str], start_index: int, end_index: int) -> tuple[int, int]:
    plists_start: int | None = None
    for index in range(start_index, end_index):
        if "{%- set plists = [" in lines[index]:
            plists_start = index
            break
    if plists_start is None:
        raise ValueError("Could not find plists declaration")

    for index in range(plists_start, end_index):
        if "] -%}" in lines[index]:
            return plists_start, index
    raise ValueError("Could not find end of plists declaration")


def _find_last_item_line(lines: list[str], plists_start: int, plists_end: int) -> int | None:
    for index in range(plists_end - 1, plists_start - 1, -1):
        stripped = lines[index].strip()
        if stripped.startswith('"') and stripped.endswith('"'):
            return index
        if stripped.startswith('"') and stripped.endswith('",'):
            return index
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--item", required=True)
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    content = config_path.read_text(encoding="utf-8")
    updated, changed = append_item_to_playlist_config(content, args.target, args.item)
    if changed:
        config_path.write_text(updated, encoding="utf-8")
        print(f"Added {args.item} to {args.target}")
    else:
        print(f"{args.item} already present in {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
