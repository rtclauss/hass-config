"""Constants for Smart Cat."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "smartcat"
LITTERROBOT_DOMAIN: Final = "litterrobot"

CONF_BACKFILL_DAYS: Final = "backfill_days"
CONF_WASTE_THRESHOLD: Final = "waste_full_threshold"
CONF_LITTER_THRESHOLD: Final = "litter_low_threshold"
CONF_RETENTION_DAYS: Final = "retention_days"

DEFAULT_BACKFILL_DAYS: Final = 1460  # 4 years, like Whisker+
DEFAULT_WASTE_THRESHOLD: Final = 80
DEFAULT_LITTER_THRESHOLD: Final = 70
DEFAULT_RETENTION_DAYS: Final = 0  # keep forever

UPDATE_INTERVAL: Final = timedelta(minutes=5)
# A robot whose activity has not been fetched for this long makes "fewer
# visits than usual" unknowable, so those insights are held back.
SYNC_STALE_AFTER: Final = timedelta(minutes=30)
# Wait for the cloud to record the activity after a clean cycle starts.
PUSH_REFRESH_DELAY: Final = 90
# Re-read this much already-fetched activity, so visits split across two
# fetches are reassembled and late-arriving events are picked up.
FETCH_OVERLAP: Final = timedelta(hours=2)
LR4_WINDOW: Final = timedelta(days=7)
# A fresh install fetches this much live history first, then backfills older.
INITIAL_LIVE_WINDOW: Final = timedelta(days=30)
LR4_WINDOW_LIMIT: Final = 1000
# Spread a multi-year backfill over several refreshes.
LR4_MAX_WINDOWS_PER_REFRESH: Final = 26
# Re-fetch an unfinished LR4 visit (no clean cycle yet) until it closes, but
# not forever if a robot never cycles.
LR4_OPEN_SEGMENT_HOLD: Final = timedelta(days=1)
LR5_PAGE_SIZE: Final = 100
LR5_MAX_PAGES_PER_REFRESH: Final = 50
# Only announce visits this recent (not backfilled history).
NEW_VISIT_EVENT_WINDOW: Final = timedelta(hours=1)

EVENT_VISIT: Final = f"{DOMAIN}_visit"
EVENT_NEW_CAT_SUSPECTED: Final = f"{DOMAIN}_new_cat_suspected"

DB_FILENAME: Final = "smartcat.db"
