"""Binary sensors for Smart Cat."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SmartCatConfigEntry, SmartCatCoordinator
from .entity import CatEntity, HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartCatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        AttentionBinarySensor(coordinator, cat_id) for cat_id in coordinator.data.cats
    ]
    entities.append(NewCatSuspectedBinarySensor(coordinator))
    async_add_entities(entities)


class AttentionBinarySensor(CatEntity, BinarySensorEntity):
    """On when a cat's pattern has changed (outlier or trend)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: SmartCatCoordinator, cat_id: str) -> None:
        """Initialise."""
        super().__init__(coordinator, cat_id, "attention")

    @property
    def is_on(self) -> bool:
        """Return True if any anomaly is active."""
        return bool(self.coordinator.data.insights[self.cat_id].anomalies)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active anomalies."""
        insights = self.coordinator.data.insights[self.cat_id]
        return {
            "kinds": [a.kind for a in insights.anomalies],
            "messages": [a.message for a in insights.anomalies],
        }


class NewCatSuspectedBinarySensor(HubEntity, BinarySensorEntity):
    """On when weigh-ins suggest a cat Smart Cat does not know yet."""

    _attr_icon = "mdi:cat"

    def __init__(self, coordinator: SmartCatCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "new_cat_suspected")

    @property
    def is_on(self) -> bool:
        """Return True if a new cat is suspected."""
        return self.coordinator.data.candidate is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the candidate's details."""
        c = self.coordinator.data.candidate
        if c is None:
            return {}
        return {
            "median_lbs": c.median_lbs,
            "spread_lbs": c.spread_lbs,
            "weigh_ins": c.count,
            "days": c.days,
            "first_seen": c.first_seen.isoformat(),
            "last_seen": c.last_seen.isoformat(),
        }
