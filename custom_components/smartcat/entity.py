"""Base entities for Smart Cat."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LITTERROBOT_DOMAIN
from .coordinator import SmartCatCoordinator


class SmartCatEntity(CoordinatorEntity[SmartCatCoordinator]):
    """Base entity."""

    _attr_has_entity_name = True


class CatEntity(SmartCatEntity):
    """An entity that belongs to one cat's device."""

    def __init__(self, coordinator: SmartCatCoordinator, cat_id: str, key: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self.cat_id = cat_id
        self._attr_translation_key = key
        self._attr_unique_id = f"cat_{cat_id}_{key}"
        cat = coordinator.data.cats[cat_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"cat_{cat_id}")},
            name=cat.name,
            manufacturer="Smart Cat",
            model="Cat profile",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Return True while the cat exists and data is fresh."""
        return super().available and self.cat_id in self.coordinator.data.insights


class RobotEntity(SmartCatEntity):
    """An entity attached to the core Whisker integration's robot device."""

    def __init__(self, coordinator: SmartCatCoordinator, serial: str, key: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self.serial = serial
        self._attr_translation_key = key
        self._attr_unique_id = f"robot_{serial}_{key}"
        # Same identifier as the core integration, so these show up on the
        # existing Litter-Robot device page.
        self._attr_device_info = DeviceInfo(identifiers={(LITTERROBOT_DOMAIN, serial)})

    @property
    def available(self) -> bool:
        """Return True while the robot is known."""
        return super().available and self.serial in self.coordinator.data.robots


class HubEntity(SmartCatEntity):
    """An entity on the Smart Cat hub device."""

    def __init__(self, coordinator: SmartCatCoordinator, key: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Smart Cat",
            manufacturer="Smart Cat",
            model="Cat insights",
            entry_type=DeviceEntryType.SERVICE,
        )
