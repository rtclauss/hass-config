"""Fetch visit history from the Whisker cloud using the core integration's login.

Smart Cat does not log in itself. It borrows the authenticated pylitterbot
`Account` from Home Assistant's core Whisker (`litterrobot`) integration
(`entry.runtime_data.account`), so there is one session and one set of
credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    LITTERROBOT_DOMAIN,
    LR4_MAX_WINDOWS_PER_REFRESH,
    LR4_WINDOW,
    LR4_WINDOW_LIMIT,
    LR5_MAX_PAGES_PER_REFRESH,
    LR5_PAGE_SIZE,
)
from .core.parse import LR4Event, lr4_event, lr4_raw_event, lr5_record_time

_LOGGER = logging.getLogger(__name__)

_LR4_ACTIVITY_QUERY = """
query GetLR4Activity(
    $serial: String!
    $startTimestamp: String
    $endTimestamp: String
    $limit: Int
    $consumer: String
) {
    getLitterRobot4Activity(
        serial: $serial
        startTimestamp: $startTimestamp
        endTimestamp: $endTimestamp
        limit: $limit
        consumer: $consumer
    ) {
        timestamp
        value
        actionValue
    }
}
"""


def get_account(hass: HomeAssistant) -> Any | None:
    """Return the pylitterbot Account of a loaded core Whisker entry."""
    for entry in hass.config_entries.async_loaded_entries(LITTERROBOT_DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if (account := getattr(coordinator, "account", None)) is not None:
            return account
    return None


def robot_kind(robot: Any) -> str | None:
    """Return 'lr4', 'lr5' or None for unsupported robots."""
    names = {cls.__name__ for cls in type(robot).__mro__}
    if "LitterRobot5" in names:
        return "lr5"
    if "LitterRobot4" in names:
        return "lr4"
    return None


def _api_ts(value: datetime) -> str:
    # The LR4 API takes "YYYY-MM-DD HH:MM:SS" in UTC and rejects ISO 8601.
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


async def fetch_lr4_events(
    robot: Any, since: datetime, now: datetime
) -> tuple[list[LR4Event], datetime]:
    """Fetch LR4 events in [since, now] in fixed windows.

    Returns the events and how far fetching got (it may stop early to spread a
    long backfill across refreshes).
    """
    events: list[LR4Event] = []
    start = since
    windows = 0
    while start < now and windows < LR4_MAX_WINDOWS_PER_REFRESH:
        end = min(start + LR4_WINDOW, now)
        rows = await _lr4_window(robot, start, end)
        events.extend(
            e for row in rows if (e := row.get("_event") or lr4_raw_event(row)) is not None
        )
        if len(rows) >= LR4_WINDOW_LIMIT:
            # Should not happen for a 7 day window; keep going but say so.
            _LOGGER.warning(
                "Litter-Robot %s returned %s activity rows for %s..%s; some may be missing",
                robot.serial,
                len(rows),
                start,
                end,
            )
        start = end
        windows += 1
    return events, start


async def fetch_lr4_events_backward(
    robot: Any, until: datetime, target: datetime
) -> tuple[list[LR4Event], datetime]:
    """Fetch LR4 events from `until` back toward `target`, newest window first.

    Used for the historical backfill, so recent history lands first and a
    multi-year backfill is spread over several refreshes. Returns the events
    and how far back fetching got.
    """
    events: list[LR4Event] = []
    end = until
    windows = 0
    while end > target and windows < LR4_MAX_WINDOWS_PER_REFRESH:
        start = max(end - LR4_WINDOW, target)
        rows = await _lr4_window(robot, start, end)
        events.extend(
            e for row in rows if (e := row.get("_event") or lr4_raw_event(row)) is not None
        )
        end = start
        windows += 1
    return events, end


async def _lr4_window(robot: Any, start: datetime, end: datetime) -> list[dict[str, Any]]:
    post = getattr(robot, "_post", None)
    if post is None:  # pragma: no cover - pylitterbot internals changed
        activities = await robot.get_activity_history(limit=LR4_WINDOW_LIMIT, start=start)
        return [
            {"timestamp": a.timestamp.isoformat(), "_event": lr4_event(a.timestamp, a.action)}
            for a in activities
            if a.timestamp <= end
        ]
    data = await post(
        json={
            "query": _LR4_ACTIVITY_QUERY,
            "variables": {
                "serial": robot.serial,
                "startTimestamp": _api_ts(start),
                "endTimestamp": _api_ts(end),
                "limit": LR4_WINDOW_LIMIT,
                "consumer": "app",
            },
        }
    )
    rows = (data or {}).get("data", {}).get("getLitterRobot4Activity") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


async def fetch_lr5_records(
    robot: Any, since: datetime, offset: int = 0
) -> tuple[list[dict[str, Any]], int, bool]:
    """Fetch LR5 activity records (newest first) from `offset` back to `since`.

    Reads at most LR5_MAX_PAGES_PER_REFRESH pages. Returns the records, the
    offset to continue from, and whether fetching reached `since` or the end
    of the feed. When it did not, the caller continues from the returned
    offset on a later refresh.
    """
    records: list[dict[str, Any]] = []
    for _ in range(LR5_MAX_PAGES_PER_REFRESH):
        batch = await robot.get_activities(limit=LR5_PAGE_SIZE, offset=offset)
        if not batch:
            return records, offset, True
        records.extend(batch)
        offset += len(batch)
        times = [t for r in batch if (t := lr5_record_time(r)) is not None]
        if len(batch) < LR5_PAGE_SIZE or (times and min(times) < since):
            return records, offset, True
    return records, offset, False


def robot_levels(robot: Any) -> tuple[float | None, float | None, int | None, bool]:
    """Return (waste %, litter %, cycle count, busy) for a robot."""

    def read(name: str) -> Any:
        try:
            return getattr(robot, name)
        except Exception:  # noqa: BLE001 - defensive against model quirks
            return None

    waste = read("waste_drawer_level")
    litter = read("litter_level")
    cycles = read("cycle_count")
    status = str(read("status_code") or "").lower()
    # Litter level is unreliable mid-cycle and while a cat is inside.
    busy = status in {"ccp", "p", "cd", "csi", "pd", "otf"}
    return (
        float(waste) if isinstance(waste, (int, float)) else None,
        float(litter) if isinstance(litter, (int, float)) else None,
        int(cycles) if isinstance(cycles, (int, float)) else None,
        busy,
    )


def lr5_cursor_from(records: list[dict[str, Any]], fallback: datetime) -> datetime:
    """Return the newest record time, or `fallback`."""
    times = [t for r in records if (t := lr5_record_time(r)) is not None]
    return max(times) if times else fallback


__all__ = [
    "fetch_lr4_events",
    "fetch_lr4_events_backward",
    "fetch_lr5_records",
    "get_account",
    "lr5_cursor_from",
    "robot_kind",
    "robot_levels",
]
