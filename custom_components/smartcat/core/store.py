"""SQLite persistence for visits, cats, level readings and sync cursors.

Kept separate from the Home Assistant recorder on purpose: the recorder purges
states (90 days in a typical config), while Whisker+ keeps up to 4 years of
history. All methods are blocking; call them from an executor.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import threading

from .models import Cat, LevelReading, Visit

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS visits (
    key TEXT PRIMARY KEY,
    robot_serial TEXT NOT NULL,
    ts REAL NOT NULL,
    weight REAL,
    duration REAL,
    source TEXT,
    whisker_pet_id TEXT,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS visits_ts ON visits (ts);
CREATE TABLE IF NOT EXISTS cats (
    cat_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    seed_lbs REAL,
    whisker_pet_id TEXT,
    active_from REAL
);
CREATE TABLE IF NOT EXISTS levels (
    robot_serial TEXT NOT NULL,
    ts REAL NOT NULL,
    waste REAL,
    litter REAL,
    cycles INTEGER,
    PRIMARY KEY (robot_serial, ts)
);
"""


def _ts(value: datetime) -> float:
    return value.timestamp()


def _dt(value: float | None) -> datetime | None:
    return None if value is None else datetime.fromtimestamp(value, UTC)


class Store:
    """Thread-safe SQLite store."""

    def __init__(self, path: str | Path) -> None:
        """Open (and create if needed) the database."""
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (k, v) VALUES ('schema', ?)",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        """Close the database."""
        with self._lock:
            self._conn.close()

    # --- meta ---------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        """Return a meta value."""
        with self._lock:
            row = self._conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str | None) -> None:
        """Set (or delete with None) a meta value."""
        with self._lock, self._conn:
            if value is None:
                self._conn.execute("DELETE FROM meta WHERE k = ?", (key,))
            else:
                self._conn.execute(
                    "INSERT INTO meta (k, v) VALUES (?, ?) "
                    "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                    (key, value),
                )

    def clear_meta_prefix(self, prefix: str) -> None:
        """Delete every meta key starting with `prefix`."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM meta WHERE k LIKE ?", (prefix + "%",))

    # --- visits -------------------------------------------------------------

    def upsert_visits(self, visits: Iterable[Visit]) -> list[Visit]:
        """Insert new visits, fill in missing details of known ones.

        Returns the visits that were new. Of two duration estimates the longer
        one wins: an estimate from a fetch that saw only part of the visit (its
        first detection fell before the fetch window) starts too late, so it
        is shorter, never longer. The raw details follow the winning estimate.
        """
        new: list[Visit] = []
        with self._lock, self._conn:
            for visit in visits:
                exists = self._conn.execute(
                    "SELECT 1 FROM visits WHERE key = ?", (visit.key,)
                ).fetchone()
                raw = json.dumps(visit.raw, default=str) if visit.raw else None
                if exists:
                    self._conn.execute(
                        "UPDATE visits SET "
                        "weight = COALESCE(weight, :weight), "
                        "raw = CASE WHEN :duration > COALESCE(duration, -1) THEN COALESCE(:raw, raw) "
                        "ELSE COALESCE(raw, :raw) END, "
                        "duration = MAX(COALESCE(duration, :duration), "
                        "COALESCE(:duration, duration)), "
                        "whisker_pet_id = COALESCE(whisker_pet_id, :pet) WHERE key = :key",
                        {
                            "weight": visit.weight_lbs,
                            "duration": visit.duration_s,
                            "raw": raw,
                            "pet": visit.whisker_pet_id,
                            "key": visit.key,
                        },
                    )
                    continue
                self._conn.execute(
                    "INSERT INTO visits (key, robot_serial, ts, weight, duration, source, "
                    "whisker_pet_id, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        visit.key,
                        visit.robot_serial,
                        _ts(visit.timestamp),
                        visit.weight_lbs,
                        visit.duration_s,
                        visit.source,
                        visit.whisker_pet_id,
                        raw,
                    ),
                )
                new.append(visit)
        return new

    def visits(self, since: datetime | None = None) -> list[Visit]:
        """Return visits in time order."""
        query = (
            "SELECT robot_serial, ts, weight, duration, source, whisker_pet_id, raw "
            "FROM visits"
        )
        params: tuple = ()
        if since is not None:
            query += " WHERE ts >= ?"
            params = (_ts(since),)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY ts", params).fetchall()
        return [
            Visit(
                serial,
                datetime.fromtimestamp(ts, UTC),
                weight,
                duration,
                source or "",
                pet,
                json.loads(raw) if raw else None,
            )
            for serial, ts, weight, duration, source, pet, raw in rows
        ]

    def delete_visits_before(self, cutoff: datetime) -> int:
        """Apply retention. Returns the number of deleted visits."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM visits WHERE ts < ?", (_ts(cutoff),))
            self._conn.execute("DELETE FROM levels WHERE ts < ?", (_ts(cutoff),))
        return cur.rowcount

    # --- cats ---------------------------------------------------------------

    def cats(self) -> list[Cat]:
        """Return all cat profiles."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT cat_id, name, seed_lbs, whisker_pet_id, active_from FROM cats "
                "ORDER BY rowid"
            ).fetchall()
        return [Cat(c, n, s, p, _dt(a)) for c, n, s, p, a in rows]

    def save_cat(self, cat: Cat) -> None:
        """Insert or update a cat profile."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO cats (cat_id, name, seed_lbs, whisker_pet_id, active_from) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(cat_id) DO UPDATE SET "
                "name = excluded.name, seed_lbs = excluded.seed_lbs, "
                "whisker_pet_id = excluded.whisker_pet_id, active_from = excluded.active_from",
                (
                    cat.cat_id,
                    cat.name,
                    cat.seed_lbs,
                    cat.whisker_pet_id,
                    _ts(cat.active_from) if cat.active_from else None,
                ),
            )

    def delete_cat(self, cat_id: str) -> bool:
        """Delete a cat profile (its visits stay and are re-attributed)."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM cats WHERE cat_id = ?", (cat_id,))
        return cur.rowcount > 0

    # --- levels -------------------------------------------------------------

    def add_level(self, reading: LevelReading) -> bool:
        """Record a level sample if it differs from the previous one."""
        with self._lock, self._conn:
            last = self._conn.execute(
                "SELECT waste, litter, cycles FROM levels WHERE robot_serial = ? "
                "ORDER BY ts DESC LIMIT 1",
                (reading.robot_serial,),
            ).fetchone()
            values = (reading.waste_pct, reading.litter_pct, reading.cycle_count)
            if last is not None and tuple(last) == values:
                return False
            self._conn.execute(
                "INSERT OR REPLACE INTO levels (robot_serial, ts, waste, litter, cycles) "
                "VALUES (?, ?, ?, ?, ?)",
                (reading.robot_serial, _ts(reading.timestamp), *values),
            )
        return True

    def levels(self, robot_serial: str, since: datetime | None = None) -> list[LevelReading]:
        """Return level samples for a robot in time order."""
        query = "SELECT ts, waste, litter, cycles FROM levels WHERE robot_serial = ?"
        params: tuple = (robot_serial,)
        if since is not None:
            query += " AND ts >= ?"
            params += (_ts(since),)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY ts", params).fetchall()
        return [
            LevelReading(robot_serial, datetime.fromtimestamp(ts, UTC), w, l, c)
            for ts, w, l, c in rows
        ]
