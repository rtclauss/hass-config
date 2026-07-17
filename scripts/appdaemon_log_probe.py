#!/usr/bin/env python3
"""Probe AppDaemon logs for recent HA websocket reconnect failures."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_SIGNATURES = (
    "Invalid response status",
    "supervisor/core/api/websocket",
    "Attempting reconnection",
)


def _parse_appdaemon_timestamp(line: str) -> datetime | None:
    if len(line) < 19:
        return None

    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def latest_recent_match(
    log_path: Path,
    *,
    signatures: Iterable[str] = DEFAULT_SIGNATURES,
    max_age_seconds: int = 600,
    max_lines: int = 1000,
    now: datetime | None = None,
) -> str:
    if not log_path.exists():
        return "clear"

    signatures = tuple(signatures)
    current_time = now or datetime.now()

    try:
        with log_path.open(encoding="utf-8", errors="replace") as handle:
            lines = deque(handle, maxlen=max_lines)
    except OSError:
        return "clear"

    for line in reversed(lines):
        if not any(signature in line for signature in signatures):
            continue

        timestamp = _parse_appdaemon_timestamp(line)
        if timestamp is None:
            continue

        age_seconds = (current_time - timestamp).total_seconds()
        if 0 <= age_seconds <= max_age_seconds:
            return timestamp.strftime("%Y-%m-%d %H:%M:%S")

        return "clear"

    return "clear"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        default="/config/logs/appdaemon_error.log",
        type=Path,
        help="AppDaemon error log path",
    )
    parser.add_argument(
        "--max-age-seconds",
        default=600,
        type=int,
        help="Ignore matching log lines older than this many seconds",
    )
    parser.add_argument(
        "--max-lines",
        default=1000,
        type=int,
        help="Only inspect this many lines from the end of the log",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        latest_recent_match(
            args.log,
            max_age_seconds=args.max_age_seconds,
            max_lines=args.max_lines,
        )
    )


if __name__ == "__main__":
    main()
