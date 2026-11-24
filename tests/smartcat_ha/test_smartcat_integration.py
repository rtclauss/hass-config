"""End-to-end tests against a real Home Assistant instance with fake robots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.smartcat.const import DOMAIN, EVENT_VISIT
from custom_components.smartcat.core.identify import identify_all
from custom_components.smartcat.core.models import Assignment

NOW = datetime(2026, 11, 23, 20, 0, tzinfo=UTC)


def api_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


class FakePet:
    def __init__(self, pet_id: str, name: str, weight: float) -> None:
        self.id, self.name, self.weight, self.is_deceased = pet_id, name, weight, False


class LitterRobot4:  # robot_kind() matches on the class name
    """A Main Level LR4 with ~4 visits/day for 20 days, ~13.1 lb (reads heavy)."""

    def __init__(self) -> None:
        self.serial, self.name = "LR4SERIAL", "Main Level"
        self.clean_cycle_wait_time_minutes = 7
        self.waste_drawer_level, self.litter_level, self.cycle_count = 24.0, 90.0, 7
        self.status_code = "rdy"
        self.rows: list[dict[str, Any]] = []
        self.listeners: list = []
        self.windows: list[tuple[str, str]] = []
        for day in range(20, 0, -1):
            for i in range(4):
                self.add_visit(NOW - timedelta(days=day, hours=-2 - 5 * i), 13.1 + (i % 3) * 0.05)

    def add_visit(self, start: datetime, weight: float) -> None:
        self.rows += [
            {"timestamp": api_ts(start), "value": "robotStatusCatDetect", "actionValue": ""},
            {"timestamp": api_ts(start + timedelta(minutes=1)), "value": "catWeight", "actionValue": str(weight)},
            {"timestamp": api_ts(start + timedelta(minutes=9)), "value": "robotCycleStatusDump", "actionValue": ""},
            {"timestamp": api_ts(start + timedelta(minutes=9)), "value": "odometerCleanCycles", "actionValue": "1"},
        ]

    async def _post(self, json: dict[str, Any]) -> dict[str, Any]:
        v = json["variables"]
        self.windows.append((v["startTimestamp"], v["endTimestamp"]))
        rows = [r for r in self.rows if v["startTimestamp"] <= r["timestamp"] <= v["endTimestamp"]]
        return {"data": {"getLitterRobot4Activity": rows}}

    def on(self, event: str, callback):
        self.listeners.append(callback)
        return lambda: None


class LitterRobot5:
    """A Basement LR5 reporting PET_VISIT records with pet ids."""

    def __init__(self) -> None:
        self.serial, self.name = "LR5SERIAL", "Basement"
        self.clean_cycle_wait_time_minutes = 7
        self.waste_drawer_level, self.litter_level, self.cycle_count = 40.0, 85.0, 30
        self.status_code = "rdy"
        self.records = [
            {
                "type": "PET_VISIT",
                "timestamp": (NOW - timedelta(days=d, hours=3)).isoformat(),
                "petId": "PET-SPLASHY",
                "weight": 1095,
                "duration": 80,
            }
            for d in range(10, 0, -1)
        ]

    async def get_activities(self, limit: int | None = None, offset: int | None = None, activity_type=None):
        newest_first = sorted(self.records, key=lambda r: r["timestamp"], reverse=True)
        return newest_first[offset or 0 : (offset or 0) + (limit or 100)]


class FakeAccount:
    def __init__(self) -> None:
        self.robots = [LitterRobot4(), LitterRobot5()]
        self.pets = [FakePet("PET-SPLASHY", "Splashy", 10.92)]

    async def disconnect(self) -> None:
        return None


class FakeCoordinator:
    def __init__(self, account: FakeAccount) -> None:
        self.account = account


@pytest.fixture
async def whisker(hass: HomeAssistant) -> FakeAccount:
    """A loaded core Whisker entry carrying a fake account."""
    account = FakeAccount()
    entry = MockConfigEntry(domain="litterrobot", title="Whisker", data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = FakeCoordinator(account)
    dev_reg = dr.async_get(hass)
    for robot in account.robots:
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("litterrobot", robot.serial)}, name=robot.name
        )
    return account


async def setup_smartcat(hass: HomeAssistant, tmp_path) -> MockConfigEntry:
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, title="Smart Cat", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(recorder_mock, hass: HomeAssistant, whisker) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.smartcat.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"waste_full_threshold": 80, "litter_low_threshold": 70, "backfill_days": 1460, "retention_days": 0},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["backfill_days"] == 1460


async def test_config_flow_requires_whisker(recorder_mock, hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "whisker_missing"


async def test_full_setup(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("America/Denver")
    entry = await setup_smartcat(hass, tmp_path)
    assert entry.state is ConfigEntryState.LOADED

    # Splashy was created from the Whisker pet profile.
    ent_reg = er.async_get(hass)
    weight_id = ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_splashy_weight")
    assert weight_id
    weight = hass.states.get(weight_id)
    # LR4 reads ~13.1, LR5 (pet id) ~10.95: the 7 day median mixes both robots.
    assert 10.5 < float(weight.state) < 13.5

    insight = hass.states.get(ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_splashy_insight"))
    assert insight.state == "normal", insight.attributes
    assert "Splashy visited" in insight.attributes["summary"]

    visits = hass.states.get(ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_splashy_visits_today"))
    assert visits.attributes["baseline_mean"] == pytest.approx(4.5, abs=1.0)
    assert sum(visits.attributes["hourly_histogram_30d"]) == 90

    last = hass.states.get(ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_splashy_last_visit_duration"))
    assert float(last.state) > 0

    # Forecast sensors land on the core integration's robot devices.
    fc_id = ent_reg.async_get_entity_id("sensor", DOMAIN, "robot_LR4SERIAL_waste_drawer_full_forecast")
    device = dr.async_get(hass).async_get(ent_reg.async_get(fc_id).device_id)
    assert ("litterrobot", "LR4SERIAL") in device.identifiers
    assert hass.states.get(fc_id).attributes["current_pct"] == 24.0

    assert hass.states.get(ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "cat_splashy_attention")).state == "off"
    new_cat_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_new_cat_suspected")
    assert hass.states.get(new_cat_id).state == "off"

    # Live: the last 30 days in 7 day windows; then the backfill walks back
    # 26 windows (6 months) per refresh toward 4 years.
    lr4 = whisker.robots[0]
    assert len(lr4.windows) == 5 + 26
    assert not entry.runtime_data.data.backfill_complete

    # Long-term statistics were imported.
    await async_wait_recording_done(hass)
    stats = await recorder_mock.async_add_executor_job(
        statistics_during_period,
        hass,
        NOW - timedelta(days=30),
        None,
        {"smartcat:splashy_visits", "smartcat:splashy_weight"},
        "day",
        None,
        {"change", "mean"},
    )
    assert sum(row["change"] for row in stats["smartcat:splashy_visits"]) == 90
    assert stats["smartcat:splashy_weight"]


async def test_live_visit_event_and_services(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    coordinator = entry.runtime_data
    # Finish the backfill.
    for _ in range(10):
        await coordinator.async_refresh()
    assert coordinator.data.backfill_complete

    events = async_capture_events(hass, EVENT_VISIT)
    lr4 = whisker.robots[0]
    freezer.move_to(NOW + timedelta(minutes=30))
    lr4.add_visit(NOW + timedelta(minutes=10), 13.12)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["cat_id"] == "splashy"
    assert events[0].data["weight_lbs"] == 13.12
    assert events[0].data["duration_s"] == pytest.approx(120)

    response = await hass.services.async_call(
        DOMAIN, "get_visits", {"cat_id": "splashy", "limit": 3}, blocking=True, return_response=True
    )
    assert len(response["visits"]) == 3
    assert response["visits"][0]["weight_lbs"] == 13.12

    # Adding a cat without a weight needs a suspected candidate.
    with pytest.raises(Exception, match="weight_lbs"):
        await hass.services.async_call(DOMAIN, "add_cat", {"name": "Kitten"}, blocking=True)

    result = await hass.services.async_call(
        DOMAIN, "add_cat", {"name": "Kitten", "weight_lbs": 6.0}, blocking=True, return_response=True
    )
    assert result["cat_id"] == "kitten"
    await hass.async_block_till_done()
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_kitten_weight")

    await hass.services.async_call(DOMAIN, "remove_cat", {"cat_id": "kitten"}, blocking=True)
    await hass.async_block_till_done()
    assert "kitten" not in entry.runtime_data.data.cats


async def test_new_cat_detected(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    lr4 = whisker.robots[0]
    for i in range(16):
        lr4.add_visit(NOW - timedelta(days=5) + timedelta(hours=7 * i, minutes=30), 6.0 + (i % 3) * 0.1)
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    ent_reg = er.async_get(hass)
    new_cat = hass.states.get(
        ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_new_cat_suspected")
    )
    assert new_cat.state == "on"
    assert new_cat.attributes["median_lbs"] == pytest.approx(6.1, abs=0.15)

    result = await hass.services.async_call(
        DOMAIN, "add_cat", {"name": "Kitten"}, blocking=True, return_response=True
    )
    assert result["seed_lbs"] == pytest.approx(6.1, abs=0.15)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.candidate is None
    assert data.insights["kitten"].total_visits == 16


async def test_refresh_between_detection_and_weigh_in_counts_one_visit(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_VISIT)
    lr4 = whisker.robots[0]
    start = NOW + timedelta(minutes=10)

    # A refresh lands after the cat was detected but before it was weighed.
    lr4.rows.append({"timestamp": api_ts(start), "value": "robotStatusCatDetect", "actionValue": ""})
    freezer.move_to(start + timedelta(seconds=30))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert events == []

    # The weigh-in and clean cycle arrive; the next refresh sees the whole visit.
    lr4.rows += [
        {"timestamp": api_ts(start + timedelta(minutes=1)), "value": "catWeight", "actionValue": "13.12"},
        {"timestamp": api_ts(start + timedelta(minutes=9)), "value": "robotCycleStatusDump", "actionValue": ""},
    ]
    freezer.move_to(start + timedelta(minutes=20))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    stored = await hass.async_add_executor_job(coordinator.store.visits, NOW)
    assert [(v.weight_lbs, v.duration_s) for v in stored if v.robot_serial == lr4.serial] == [
        (13.12, pytest.approx(120))
    ]
    assert len(events) == 1


async def test_lr5_backfill_continues_past_the_page_limit(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    lr5 = whisker.robots[1]
    lr5.records = [
        {
            "type": "PET_VISIT",
            "timestamp": (NOW - timedelta(days=d, hours=3)).isoformat(),
            "petId": "PET-SPLASHY",
            "weight": 1095,
            "duration": 80,
        }
        for d in range(40, 0, -1)
    ]
    freezer.move_to(NOW)
    # Two pages of five per refresh: 40 records need several refreshes.
    with (
        patch("custom_components.smartcat.whisker.LR5_PAGE_SIZE", 5),
        patch("custom_components.smartcat.whisker.LR5_MAX_PAGES_PER_REFRESH", 2),
        patch("custom_components.smartcat.coordinator.LR5_PAGE_SIZE", 5),
    ):
        entry = await setup_smartcat(hass, tmp_path)
        coordinator = entry.runtime_data
        assert not coordinator.data.backfill_complete
        for step in range(12):
            # New visits keep arriving, shifting older records to higher offsets.
            lr5.records.append(
                {
                    "type": "PET_VISIT",
                    "timestamp": (NOW + timedelta(minutes=10 * step + 5)).isoformat(),
                    "petId": "PET-SPLASHY",
                    "weight": 1095,
                    "duration": 80,
                }
            )
            freezer.move_to(NOW + timedelta(minutes=10 * step + 6))
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    stored = await hass.async_add_executor_job(coordinator.store.visits)
    assert len([v for v in stored if v.robot_serial == lr5.serial]) == 40 + 12


async def test_statistics_drop_hours_whose_visits_moved_to_another_cat(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    coordinator = entry.runtime_data
    store = coordinator.store
    cats = await hass.async_add_executor_job(store.cats)
    visits = await hass.async_add_executor_job(store.visits)
    assignments, _ = identify_all(cats, visits)
    moved = next(v for v in visits if v.robot_serial == "LR4SERIAL")
    hour = moved.timestamp.replace(minute=0, second=0, microsecond=0)

    async def splashy_hours() -> set[datetime]:
        await async_wait_recording_done(hass)
        stats = await recorder_mock.async_add_executor_job(
            statistics_during_period,
            hass,
            hour - timedelta(hours=1),
            hour + timedelta(hours=2),
            {"smartcat:splashy_visits"},
            "hour",
            None,
            {"state"},
        )
        return {
            datetime.fromtimestamp(row["start"], UTC)
            for row in stats.get("smartcat:splashy_visits", [])
            if row["state"]
        }

    assert hour in await splashy_hours()

    # The visit now belongs to another cat: Splashy's row for that hour goes.
    assignments[moved.key] = Assignment("kitten", 0.9, "matched", weight_trusted=True)
    coordinator._publish_statistics(cats, visits, assignments)
    assert hour not in await splashy_hours()


async def test_removing_a_whisker_cat_is_not_undone(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    assert "splashy" in entry.runtime_data.data.cats

    await hass.services.async_call(DOMAIN, "remove_cat", {"cat_id": "splashy"}, blocking=True)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    assert "splashy" not in coordinator.data.cats
    assert await hass.async_add_executor_job(coordinator.store.cats) == []

    # Adding the cat back by name re-links the Whisker pet profile.
    await hass.services.async_call(
        DOMAIN, "add_cat", {"name": "Splashy", "weight_lbs": 11.0}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    (cat,) = await hass.async_add_executor_job(entry.runtime_data.store.cats)
    assert cat.whisker_pet_id == "PET-SPLASHY"


async def test_raising_the_backfill_depth_resumes_lr5_history(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    lr5 = whisker.robots[1]
    lr5.records = [
        {
            "type": "PET_VISIT",
            "timestamp": (NOW - timedelta(days=d, hours=3)).isoformat(),
            "petId": "PET-SPLASHY",
            "weight": 1095,
            "duration": 80,
        }
        for d in range(90, 0, -1)
    ]
    freezer.move_to(NOW)
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, title="Smart Cat", data={}, options={"backfill_days": 30})
    entry.add_to_hass(hass)

    async def lr5_visits() -> int:
        stored = await hass.async_add_executor_job(entry.runtime_data.store.visits)
        return len([v for v in stored if v.robot_serial == lr5.serial])

    # Pages of five, so the live fetch only reads the newest records.
    with (
        patch("custom_components.smartcat.whisker.LR5_PAGE_SIZE", 5),
        patch("custom_components.smartcat.whisker.LR5_MAX_PAGES_PER_REFRESH", 4),
        patch("custom_components.smartcat.coordinator.LR5_PAGE_SIZE", 5),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        for _ in range(3):
            await entry.runtime_data.async_refresh()
        assert entry.runtime_data.data.backfill_complete
        assert await lr5_visits() == 29

        hass.config_entries.async_update_entry(entry, options={**entry.options, "backfill_days": 120})
        await hass.async_block_till_done()
        for _ in range(6):
            await entry.runtime_data.async_refresh()
        assert entry.runtime_data.data.backfill_complete
        assert await lr5_visits() == 90


async def test_failed_syncs_do_not_report_a_missing_cat(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    coordinator = entry.runtime_data
    lr4, lr5 = whisker.robots

    async def broken(*_args, **_kwargs):
        raise ConnectionError("Whisker API unavailable")

    # Both robots work and the cat really stopped visiting: reported.
    freezer.move_to(NOW + timedelta(days=2))
    await coordinator.async_refresh()
    kinds = {a.kind for a in coordinator.data.insights["splashy"].anomalies}
    assert "no_recent_visits" in kinds

    # One robot cannot be read: the cat may be using it, so absence is unknown.
    lr5.get_activities = broken
    freezer.move_to(NOW + timedelta(days=2, hours=1))
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.stale_robots == ["Basement"]
    kinds = {a.kind for a in coordinator.data.insights["splashy"].anomalies}
    assert not kinds & {"no_recent_visits", "frequency_low"}

    # Neither robot can be read: the update fails and entities go unavailable.
    lr4._post = broken
    freezer.move_to(NOW + timedelta(days=2, hours=2))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    ent_reg = er.async_get(hass)
    attention = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "cat_splashy_attention")
    assert hass.states.get(attention).state == "unavailable"


async def test_cat_imported_later_gets_entities(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    entry = await setup_smartcat(hass, tmp_path)
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_mochi_weight") is None

    # A second pet profile is added in the Whisker app while Smart Cat runs.
    whisker.pets.append(FakePet("PET-MOCHI", "Mochi", 7.5))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, "cat_mochi_weight")
    assert ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "cat_mochi_attention")


async def test_lr5_capped_live_fetch_does_not_skip_records(
    recorder_mock, hass: HomeAssistant, whisker: FakeAccount, tmp_path, freezer: FrozenDateTimeFactory
) -> None:
    lr5 = whisker.robots[1]
    freezer.move_to(NOW)

    def record(ts: datetime) -> dict[str, Any]:
        return {"type": "PET_VISIT", "timestamp": ts.isoformat(), "petId": "PET-SPLASHY", "weight": 1095, "duration": 80}

    async def lr5_frontier() -> str | None:
        return await hass.async_add_executor_job(
            entry.runtime_data.store.get_meta, f"backfill:{lr5.serial}"
        )

    async def lr5_visits() -> int:
        stored = await hass.async_add_executor_job(entry.runtime_data.store.visits)
        return len([v for v in stored if v.robot_serial == lr5.serial])

    with (
        patch("custom_components.smartcat.whisker.LR5_PAGE_SIZE", 5),
        # 20 records per refresh: more than the 2 h overlap re-read (12).
        patch("custom_components.smartcat.whisker.LR5_MAX_PAGES_PER_REFRESH", 4),
        patch("custom_components.smartcat.coordinator.LR5_PAGE_SIZE", 5),
    ):
        entry = await setup_smartcat(hass, tmp_path)
        for _ in range(3):
            await entry.runtime_data.async_refresh()
        assert await lr5_frontier() is None
        assert await lr5_visits() == 10

        # A long outage: 30 records arrive, more than one refresh reads (20).
        lr5.records += [record(NOW + timedelta(minutes=10 * i)) for i in range(1, 31)]
        for step in range(6):
            freezer.move_to(NOW + timedelta(hours=6, minutes=step))
            await entry.runtime_data.async_refresh()
        assert await lr5_frontier() is None
        assert await lr5_visits() == 40
