"""Sensors for Smart Cat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RobotState, SmartCatConfigEntry, SmartCatCoordinator
from .core.analytics import ANOMALY_ORDER, STATUS_INSUFFICIENT, STATUS_NORMAL, CatInsights
from .core.forecast import LevelForecast
from .entity import CatEntity, HubEntity, RobotEntity

INSIGHT_OPTIONS = [STATUS_NORMAL, STATUS_INSUFFICIENT, *ANOMALY_ORDER]


def _summary(name: str, i: CatInsights) -> str:
    parts = [f"{name} visited {i.visits_today} time{'s' if i.visits_today != 1 else ''} today"]
    if i.baseline_mean is not None and i.baseline_days >= 7:
        parts[0] += f" (usually {i.baseline_mean:.1f})"
    if i.avg_duration_today_s:
        parts.append(f"averaging {i.avg_duration_today_s / 60:.1f} min")
    if i.weight_lbs:
        parts.append(f"weighing {i.weight_lbs:.1f} lb")
    text = ", ".join(parts) + "."
    if i.anomalies:
        text += " " + " ".join(a.message for a in i.anomalies)
    return text


@dataclass(frozen=True, kw_only=True)
class CatSensorDescription(SensorEntityDescription):
    """Describes a per-cat sensor."""

    value_fn: Callable[[CatInsights], Any]
    attrs_fn: Callable[[CatInsights, str], dict[str, Any]] | None = None


def _last_visit_attrs(i: CatInsights, _: str) -> dict[str, Any]:
    v = i.last_visit
    if v is None:
        return {}
    return {
        "weight_lbs": v.weight_lbs,
        "duration_s": v.duration_s,
        "robot_serial": v.robot_serial,
        "confidence": i.last_visit_confidence,
    }


CAT_SENSORS: tuple[CatSensorDescription, ...] = (
    CatSensorDescription(
        key="visits_today",
        icon="mdi:cat",
        native_unit_of_measurement="visits",
        value_fn=lambda i: i.visits_today,
        attrs_fn=lambda i, _: {
            "visits_yesterday": i.visits_yesterday,
            "baseline_mean": i.baseline_mean,
            "baseline_std": i.baseline_std,
            "baseline_days": i.baseline_days,
            "daily_counts": i.daily_counts,
            "hourly_histogram_30d": i.hourly_histogram,
            "total_visits": i.total_visits,
            "first_visit": i.first_visit.isoformat() if i.first_visit else None,
        },
    ),
    CatSensorDescription(
        key="last_visit",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda i: i.last_visit.timestamp if i.last_visit else None,
        attrs_fn=_last_visit_attrs,
    ),
    CatSensorDescription(
        key="last_visit_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=lambda i: i.last_visit.duration_s if i.last_visit else None,
    ),
    CatSensorDescription(
        key="average_visit_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=lambda i: i.avg_duration_7d_s,
        attrs_fn=lambda i, _: {
            "today_s": i.avg_duration_today_s,
            "median_30d_s": i.median_duration_30d_s,
        },
    ),
    CatSensorDescription(
        key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        suggested_display_precision=1,
        value_fn=lambda i: i.weight_lbs,
        attrs_fn=lambda i, _: {
            "trend_lbs_per_week": i.weight_trend_lbs_per_week,
            "change_30d_pct": i.weight_change_30d_pct,
        },
    ),
    CatSensorDescription(
        key="weight_trend",
        icon="mdi:chart-line",
        native_unit_of_measurement="lb/wk",
        suggested_display_precision=2,
        value_fn=lambda i: i.weight_trend_lbs_per_week,
    ),
    CatSensorDescription(
        key="insight",
        device_class=SensorDeviceClass.ENUM,
        options=INSIGHT_OPTIONS,
        icon="mdi:heart-pulse",
        value_fn=lambda i: i.status,
        attrs_fn=lambda i, name: {
            "summary": _summary(name, i),
            "anomalies": [{"kind": a.kind, "message": a.message, **a.data} for a in i.anomalies],
            "usual_gap_hours": i.usual_gap_hours,
        },
    ),
)


@dataclass(frozen=True, kw_only=True)
class RobotSensorDescription(SensorEntityDescription):
    """Describes a per-robot sensor."""

    value_fn: Callable[[RobotState], Any]
    attrs_fn: Callable[[RobotState], dict[str, Any]] | None = None


def _forecast_attrs(fc: LevelForecast) -> dict[str, Any]:
    return {
        "current_pct": fc.current,
        "threshold_pct": fc.threshold,
        "days_remaining": fc.days_remaining,
        "rate_per_cycle_pct": fc.rate_per_cycle,
        "rate_per_day_pct": fc.rate_per_day,
        "cycles_per_day": fc.cycles_per_day,
        "fill_period_start": fc.period_start.isoformat() if fc.period_start else None,
        "samples": fc.points,
        "method": fc.method,
    }


ROBOT_SENSORS: tuple[RobotSensorDescription, ...] = (
    RobotSensorDescription(
        key="waste_drawer_full_forecast",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:delete-clock",
        value_fn=lambda r: r.waste.eta,
        attrs_fn=lambda r: _forecast_attrs(r.waste),
    ),
    RobotSensorDescription(
        key="litter_refill_forecast",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:shovel",
        value_fn=lambda r: r.litter.eta,
        attrs_fn=lambda r: _forecast_attrs(r.litter),
    ),
    RobotSensorDescription(
        key="cycles_per_day",
        icon="mdi:rotate-right",
        native_unit_of_measurement="cycles/d",
        suggested_display_precision=1,
        value_fn=lambda r: r.cycles_per_day,
    ),
    RobotSensorDescription(
        key="robot_visits_today",
        icon="mdi:paw",
        native_unit_of_measurement="visits",
        value_fn=lambda r: r.visits_today,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartCatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    data = coordinator.data
    entities: list[SensorEntity] = [
        CatSensor(coordinator, cat_id, desc) for cat_id in data.cats for desc in CAT_SENSORS
    ]
    entities += [
        RobotSensor(coordinator, serial, desc) for serial in data.robots for desc in ROBOT_SENSORS
    ]
    entities.append(UnassignedVisitsSensor(coordinator))
    async_add_entities(entities)


class CatSensor(CatEntity, SensorEntity):
    """A per-cat sensor."""

    entity_description: CatSensorDescription

    def __init__(self, coordinator: SmartCatCoordinator, cat_id: str, desc: CatSensorDescription) -> None:
        """Initialise."""
        super().__init__(coordinator, cat_id, desc.key)
        self.entity_description = desc

    @property
    def _insights(self) -> CatInsights:
        return self.coordinator.data.insights[self.cat_id]

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self._insights)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        name = self.coordinator.data.cats[self.cat_id].name
        return self.entity_description.attrs_fn(self._insights, name)


class RobotSensor(RobotEntity, SensorEntity):
    """A per-robot sensor."""

    entity_description: RobotSensorDescription

    def __init__(self, coordinator: SmartCatCoordinator, serial: str, desc: RobotSensorDescription) -> None:
        """Initialise."""
        super().__init__(coordinator, serial, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> datetime | float | None:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data.robots[self.serial])

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data.robots[self.serial])


class UnassignedVisitsSensor(HubEntity, SensorEntity):
    """Visits in the last 7 days that no cat explains."""

    _attr_icon = "mdi:help-circle-outline"
    _attr_native_unit_of_measurement = "visits"

    def __init__(self, coordinator: SmartCatCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "unassigned_visits")

    @property
    def native_value(self) -> int:
        """Return the state."""
        return self.coordinator.data.unassigned_7d

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        data = self.coordinator.data
        return {"total_visits": data.total_visits, "backfill_complete": data.backfill_complete}
