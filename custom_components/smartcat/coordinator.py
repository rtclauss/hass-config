"""Smart Cat coordinator: sync Whisker activity, then derive everything else."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BACKFILL_DAYS,
    CONF_LITTER_THRESHOLD,
    CONF_RETENTION_DAYS,
    CONF_WASTE_THRESHOLD,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_LITTER_THRESHOLD,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_WASTE_THRESHOLD,
    DOMAIN,
    EVENT_NEW_CAT_SUSPECTED,
    EVENT_VISIT,
    FETCH_OVERLAP,
    INITIAL_LIVE_WINDOW,
    NEW_VISIT_EVENT_WINDOW,
    PUSH_REFRESH_DELAY,
    UPDATE_INTERVAL,
)
from .core.analytics import CatInsights, cat_insights
from .core.forecast import LevelForecast, cycles_per_day, forecast_level
from .core.identify import Identifier, identify_all
from .core.models import Assignment, Cat, LevelReading, NewCatCandidate, Visit
from .core.parse import lr4_visits, lr5_visits
from .core.store import Store
from .statistics import async_publish_cat_statistics
from .whisker import (
    fetch_lr4_events,
    fetch_lr4_events_backward,
    fetch_lr5_records,
    get_account,
    lr5_cursor_from,
    robot_kind,
    robot_levels,
)

_LOGGER = logging.getLogger(__name__)

type SmartCatConfigEntry = ConfigEntry[SmartCatCoordinator]


@dataclass(slots=True)
class RobotState:
    """Derived state for one Litter-Robot."""

    serial: str
    name: str
    kind: str
    waste: LevelForecast
    litter: LevelForecast
    cycles_per_day: float | None
    visits_today: int = 0


@dataclass(slots=True)
class SmartCatData:
    """Everything the entities need."""

    cats: dict[str, Cat] = field(default_factory=dict)
    insights: dict[str, CatInsights] = field(default_factory=dict)
    robots: dict[str, RobotState] = field(default_factory=dict)
    candidate: NewCatCandidate | None = None
    unassigned_7d: int = 0
    backfill_complete: bool = False
    total_visits: int = 0


def slugify_cat(name: str, taken: set[str]) -> str:
    """Return a unique, statistic-id safe slug for a cat name."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "cat"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    return slug


class SmartCatCoordinator(DataUpdateCoordinator[SmartCatData]):
    """Coordinates syncing and analysis."""

    config_entry: SmartCatConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SmartCatConfigEntry, store: Store) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=30, immediate=False),
        )
        self.store = store
        self.assignments: dict[str, Assignment] = {}
        self.identifier: Identifier | None = None
        self.visits: list[Visit] = []
        self._published: dict[str, dict[str, str | None]] = {}
        self._started = dt_util.utcnow()
        self._unsubs: list[Callable[[], None]] = []
        self._last_status: dict[str, str | None] = {}
        self._candidate_announced: datetime | None = None

    # --- options ------------------------------------------------------------

    def _opt(self, key: str, default: Any) -> Any:
        return self.config_entry.options.get(key, default)

    @property
    def backfill_days(self) -> int:
        """Return how far back to backfill."""
        return int(self._opt(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS))

    # --- store helpers (executor) --------------------------------------------

    async def _run(self, func: Callable[..., Any], *args: Any) -> Any:
        return await self.hass.async_add_executor_job(func, *args)

    # --- update -------------------------------------------------------------

    async def _async_update_data(self) -> SmartCatData:
        account = get_account(self.hass)
        if account is None:
            raise UpdateFailed("The Whisker (litterrobot) integration is not loaded")

        now = dt_util.utcnow()
        await self._sync_cats(account)
        new_visits: list[Visit] = []
        robots: dict[str, tuple[str, str]] = {}
        backfill_complete = True
        for robot in list(getattr(account, "robots", [])):
            kind = robot_kind(robot)
            if kind is None:
                continue
            robots[robot.serial] = (robot.name, kind)
            self._subscribe(robot)
            try:
                inserted, done = await self._sync_robot(robot, kind, now)
            except Exception as err:  # noqa: BLE001 - one robot must not block others
                _LOGGER.warning("Could not sync activity for %s: %s", robot.name, err)
                continue
            new_visits.extend(inserted)
            backfill_complete &= done
            await self._record_levels(robot, now)

        if retention := int(self._opt(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)):
            await self._run(self.store.delete_visits_before, now - timedelta(days=retention))

        return await self._analyse(now, robots, new_visits, backfill_complete)

    async def _sync_cats(self, account: Any) -> None:
        """Create cat profiles for Whisker pet profiles we have not seen."""
        cats = await self._run(self.store.cats)
        known = {c.whisker_pet_id for c in cats if c.whisker_pet_id}
        taken = {c.cat_id for c in cats}
        for pet in getattr(account, "pets", []) or []:
            if pet.id in known or getattr(pet, "is_deceased", False):
                continue
            # A profile with the same name (created by hand) adopts the pet id.
            same = next((c for c in cats if c.name.lower() == pet.name.lower() and not c.whisker_pet_id), None)
            if same:
                same.whisker_pet_id = pet.id
                await self._run(self.store.save_cat, same)
                continue
            try:
                weight = float(pet.weight) or None
            except (TypeError, ValueError):
                weight = None
            cat = Cat(slugify_cat(pet.name, taken), pet.name, weight, pet.id, None)
            taken.add(cat.cat_id)
            await self._run(self.store.save_cat, cat)
            _LOGGER.info("Created cat profile %s from Whisker pet profile", cat.name)

    async def _sync_robot(self, robot: Any, kind: str, now: datetime) -> tuple[list[Visit], bool]:
        """Fetch new activity for one robot. Returns (new visits, backfill done).

        Two cursors per robot: a live cursor that moves forward with new
        activity, and a backfill frontier that walks back toward the backfill
        depth a few months per refresh. A fresh install therefore shows the
        last month right away and fills in older history over the next hour.
        """
        live_key, back_key = f"cursor:{robot.serial}", f"backfill:{robot.serial}"
        override = await self._run(self.store.get_meta, "backfill_days")
        target = now - timedelta(days=int(override or self.backfill_days))
        cursor = await self._run(self.store.get_meta, live_key)
        if cursor:
            since = datetime.fromisoformat(cursor) - FETCH_OVERLAP
        else:
            since = max(target, now - INITIAL_LIVE_WINDOW)
            await self._run(self.store.set_meta, back_key, since.isoformat())

        visits: list[Visit]
        if kind == "lr4":
            wait = robot.clean_cycle_wait_time_minutes
            events, reached = await fetch_lr4_events(robot, since, now)
            visits = lr4_visits(robot.serial, events, wait)
            new_cursor = reached
            frontier_text = await self._run(self.store.get_meta, back_key)
            frontier = datetime.fromisoformat(frontier_text) if frontier_text else target
            if frontier > target:
                old_events, frontier = await fetch_lr4_events_backward(robot, frontier, target)
                visits += lr4_visits(robot.serial, old_events, wait)
                await self._run(self.store.set_meta, back_key, frontier.isoformat())
            done = frontier <= target
        else:
            # LR5 pages newest first, so a deep first fetch is still recent-first.
            if not cursor:
                since = target
            records = await fetch_lr5_records(robot, since)
            visits = [v for v in lr5_visits(robot.serial, records) if v.timestamp >= since]
            new_cursor = lr5_cursor_from(records, since + FETCH_OVERLAP)
            done = True
        inserted = await self._run(self.store.upsert_visits, visits)
        await self._run(self.store.set_meta, live_key, new_cursor.isoformat())
        if inserted:
            _LOGGER.debug("%s: %s new visits", robot.name, len(inserted))
        return inserted, done

    async def _record_levels(self, robot: Any, now: datetime) -> None:
        waste, litter, cycles, busy = robot_levels(robot)
        if busy or (waste is None and litter is None):
            return
        await self._run(
            self.store.add_level, LevelReading(robot.serial, now, waste, litter, cycles)
        )

    async def _analyse(
        self,
        now: datetime,
        robots: dict[str, tuple[str, str]],
        new_visits: list[Visit],
        backfill_complete: bool,
    ) -> SmartCatData:
        cats = await self._run(self.store.cats)
        visits = await self._run(self.store.visits)
        assignments, identifier = await self._run(identify_all, cats, visits)
        tz = dt_util.get_default_time_zone()
        data = SmartCatData(
            cats={c.cat_id: c for c in cats},
            backfill_complete=backfill_complete,
            total_visits=len(visits),
        )

        by_cat: dict[str, list[Visit]] = {c.cat_id: [] for c in cats}
        week_ago = now - timedelta(days=7)
        for visit in visits:
            cat_id = assignments[visit.key].cat_id
            if cat_id in by_cat:
                by_cat[cat_id].append(visit)
            elif visit.timestamp >= week_ago:
                data.unassigned_7d += 1
        for cat in cats:
            data.insights[cat.cat_id] = await self._run(
                cat_insights, cat.cat_id, by_cat[cat.cat_id], assignments, now, tz
            )
        data.candidate = identifier.new_cat_candidate(now)

        waste_at = float(self._opt(CONF_WASTE_THRESHOLD, DEFAULT_WASTE_THRESHOLD))
        litter_at = float(self._opt(CONF_LITTER_THRESHOLD, DEFAULT_LITTER_THRESHOLD))
        today = dt_util.start_of_local_day()
        for serial, (name, kind) in robots.items():
            levels = await self._run(self.store.levels, serial, now - timedelta(days=120))
            robot_visits = [v for v in visits if v.robot_serial == serial]
            recent = [v for v in robot_visits if v.timestamp >= now - timedelta(days=14)]
            fallback = None
            if recent:
                span = max((now - recent[0].timestamp).total_seconds() / 86400, 1.0)
                fallback = round(len(recent) / span, 2)
            rate = cycles_per_day(levels, now, fallback)
            data.robots[serial] = RobotState(
                serial,
                name,
                kind,
                forecast_level(levels, waste=True, threshold=waste_at, now=now, cycle_rate=rate),
                forecast_level(levels, waste=False, threshold=litter_at, now=now, cycle_rate=rate),
                rate,
                sum(1 for v in robot_visits if v.timestamp >= today),
            )

        self.assignments, self.identifier, self.visits = assignments, identifier, visits
        self._fire_visit_events(new_visits, assignments, data.cats, now)
        self._announce_candidate(data.candidate)
        self._publish_statistics(cats, visits, assignments)
        return data

    # --- events -------------------------------------------------------------

    @callback
    def _fire_visit_events(
        self,
        new_visits: list[Visit],
        assignments: dict[str, Assignment],
        cats: dict[str, Cat],
        now: datetime,
    ) -> None:
        for visit in sorted(new_visits, key=lambda v: v.timestamp):
            if now - visit.timestamp > NEW_VISIT_EVENT_WINDOW:
                continue  # backfilled history
            assignment = assignments.get(visit.key)
            cat = cats.get(assignment.cat_id) if assignment and assignment.cat_id else None
            self.hass.bus.async_fire(
                EVENT_VISIT,
                {
                    "cat_id": cat.cat_id if cat else None,
                    "cat_name": cat.name if cat else None,
                    "robot_serial": visit.robot_serial,
                    "timestamp": visit.timestamp.isoformat(),
                    "weight_lbs": visit.weight_lbs,
                    "duration_s": visit.duration_s,
                    "confidence": assignment.confidence if assignment else 0.0,
                    "method": assignment.method if assignment else "unknown",
                },
            )

    @callback
    def _announce_candidate(self, candidate: NewCatCandidate | None) -> None:
        if candidate is None:
            self._candidate_announced = None
            return
        if self._candidate_announced == candidate.first_seen:
            return
        self._candidate_announced = candidate.first_seen
        self.hass.bus.async_fire(
            EVENT_NEW_CAT_SUSPECTED,
            {
                "median_lbs": candidate.median_lbs,
                "count": candidate.count,
                "days": candidate.days,
                "first_seen": candidate.first_seen.isoformat(),
            },
        )

    # --- statistics ---------------------------------------------------------

    @callback
    def _publish_statistics(
        self, cats: list[Cat], visits: list[Visit], assignments: dict[str, Assignment]
    ) -> None:
        """Import statistics from the earliest hour whose attribution changed."""
        for cat in cats:
            current = {
                v.key: f"{assignments[v.key].method}:{v.weight_lbs}:{v.duration_s}"
                for v in visits
                if assignments[v.key].cat_id == cat.cat_id
            }
            previous = self._published.get(cat.cat_id)
            if previous is None:
                since = None  # first run: publish everything
            else:
                changed = {k for k in current.keys() | previous.keys() if current.get(k) != previous.get(k)}
                if not changed:
                    continue
                since = min(datetime.fromtimestamp(int(k.rsplit(":", 1)[1]), UTC) for k in changed)
            async_publish_cat_statistics(self.hass, cat, visits, assignments, since)
            self._published[cat.cat_id] = current

    # --- push ---------------------------------------------------------------

    @callback
    def _subscribe(self, robot: Any) -> None:
        """Refresh soon after a clean cycle starts (the visit just ended)."""
        if robot.serial in self._last_status or not hasattr(robot, "on"):
            return
        self._last_status[robot.serial] = getattr(robot, "status_code", None)

        def on_update(*_: Any) -> None:
            status = getattr(robot, "status_code", None)
            previous = self._last_status.get(robot.serial)
            self._last_status[robot.serial] = status
            if status != previous and str(status).lower() in {"ccp", "cst", "rdy"}:
                self.hass.loop.call_soon_threadsafe(self._schedule_refresh_soon)

        self._unsubs.append(robot.on("update", on_update))

    @callback
    def _schedule_refresh_soon(self) -> None:
        async def _refresh(_: datetime) -> None:
            await self.async_request_refresh()

        self._unsubs.append(async_call_later(self.hass, PUSH_REFRESH_DELAY, _refresh))

    @callback
    def async_shutdown_listeners(self) -> None:
        """Remove robot listeners and timers."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # --- service helpers ------------------------------------------------------

    async def async_reset_cursors(self, days: int) -> None:
        """Re-fetch history from `days` ago (missing visits are added)."""
        await self._run(self.store.clear_meta_prefix, "cursor:")
        await self._run(self.store.clear_meta_prefix, "backfill:")
        await self._run(self.store.set_meta, "backfill_days", str(days))
        self._published.clear()
