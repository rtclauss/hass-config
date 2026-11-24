"""Smart Cat services: manage cat profiles, backfill, query visits."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SmartCatCoordinator, slugify_cat
from .core.models import Cat

SERVICE_ADD_CAT = "add_cat"
SERVICE_RENAME_CAT = "rename_cat"
SERVICE_REMOVE_CAT = "remove_cat"
SERVICE_BACKFILL = "backfill"
SERVICE_GET_VISITS = "get_visits"

ADD_CAT_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("weight_lbs"): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=40)),
        vol.Optional("active_from"): cv.datetime,
    }
)
RENAME_SCHEMA = vol.Schema({vol.Required("cat_id"): cv.string, vol.Required("name"): cv.string})
REMOVE_SCHEMA = vol.Schema({vol.Required("cat_id"): cv.string})
BACKFILL_SCHEMA = vol.Schema(
    {vol.Required("days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3650))}
)
GET_VISITS_SCHEMA = vol.Schema(
    {
        vol.Optional("cat_id"): cv.string,
        vol.Optional("start"): cv.datetime,
        vol.Optional("end"): cv.datetime,
        vol.Optional("limit", default=500): vol.All(vol.Coerce(int), vol.Range(min=1, max=20000)),
    }
)


def _coordinator(hass: HomeAssistant) -> SmartCatCoordinator:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise ServiceValidationError("Smart Cat is not set up")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone())


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Smart Cat services."""

    async def add_cat(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass)
        cats = await hass.async_add_executor_job(coordinator.store.cats)
        name = call.data["name"].strip()
        if any(c.name.lower() == name.lower() for c in cats):
            raise ServiceValidationError(f"A cat named {name} already exists")
        candidate = coordinator.data.candidate if coordinator.data else None
        weight = call.data.get("weight_lbs")
        active_from = _aware(call.data.get("active_from"))
        if weight is None:
            if candidate is None:
                raise ServiceValidationError(
                    "Give weight_lbs, or wait until Smart Cat suspects a new cat"
                )
            weight = candidate.median_lbs
            active_from = active_from or candidate.first_seen
        cat = Cat(
            slugify_cat(name, {c.cat_id for c in cats}),
            name,
            float(weight),
            None,
            active_from or dt_util.utcnow(),
        )
        await hass.async_add_executor_job(coordinator.store.save_cat, cat)
        hass.config_entries.async_schedule_reload(coordinator.config_entry.entry_id)
        return {"cat_id": cat.cat_id, "seed_lbs": cat.seed_lbs, "active_from": cat.active_from.isoformat()}

    async def rename_cat(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        cats = {c.cat_id: c for c in await hass.async_add_executor_job(coordinator.store.cats)}
        if (cat := cats.get(call.data["cat_id"])) is None:
            raise ServiceValidationError(f"Unknown cat_id {call.data['cat_id']}")
        cat.name = call.data["name"].strip()
        await hass.async_add_executor_job(coordinator.store.save_cat, cat)
        hass.config_entries.async_schedule_reload(coordinator.config_entry.entry_id)

    async def remove_cat(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        if not await hass.async_add_executor_job(coordinator.store.delete_cat, call.data["cat_id"]):
            raise ServiceValidationError(f"Unknown cat_id {call.data['cat_id']}")
        hass.config_entries.async_schedule_reload(coordinator.config_entry.entry_id)

    async def backfill(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        await coordinator.async_reset_cursors(call.data["days"])
        await coordinator.async_request_refresh()

    async def get_visits(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass)
        start = _aware(call.data.get("start"))
        end = _aware(call.data.get("end"))
        cat_id = call.data.get("cat_id")
        rows: list[dict[str, Any]] = []
        for visit in reversed(coordinator.visits):
            if start and visit.timestamp < start:
                break
            if end and visit.timestamp > end:
                continue
            assignment = coordinator.assignments.get(visit.key)
            if cat_id and (assignment is None or assignment.cat_id != cat_id):
                continue
            rows.append(
                {
                    "timestamp": visit.timestamp.isoformat(),
                    "robot_serial": visit.robot_serial,
                    "cat_id": assignment.cat_id if assignment else None,
                    "confidence": assignment.confidence if assignment else 0.0,
                    "method": assignment.method if assignment else "unknown",
                    "weight_lbs": visit.weight_lbs,
                    "duration_s": visit.duration_s,
                }
            )
            if len(rows) >= call.data["limit"]:
                break
        return {"visits": rows}

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_CAT, add_cat, ADD_CAT_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, SERVICE_RENAME_CAT, rename_cat, RENAME_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_CAT, remove_cat, REMOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_BACKFILL, backfill, BACKFILL_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_GET_VISITS, get_visits, GET_VISITS_SCHEMA, supports_response=SupportsResponse.ONLY
    )
