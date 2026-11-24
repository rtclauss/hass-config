"""Base entities for Smart Cat."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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


def robot_device(hass: HomeAssistant, serial: str) -> dr.DeviceEntry | None:
    """Return the core Whisker integration's device for a robot, if any."""
    registry = dr.async_get(hass)
    for entry in hass.config_entries.async_entries(LITTERROBOT_DOMAIN):
        device = registry.async_get_device_by_identifier((LITTERROBOT_DOMAIN, serial), entry.entry_id)
        if device is not None:
            return device
    return None


class RobotEntity(SmartCatEntity):
    """An entity attached to the core Whisker integration's robot device."""

    def __init__(self, coordinator: SmartCatCoordinator, serial: str, key: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self.serial = serial
        self._attr_translation_key = key
        self._attr_unique_id = f"robot_{serial}_{key}"
        # Show up on the core Whisker integration's robot device. Device
        # identifiers are scoped per config entry, so identifier-only device
        # info would create a second device named after this config entry
        # ("Smart Cat"); attach to the existing device entry instead.
        if (device := robot_device(coordinator.hass, serial)) is not None:
            self.device_entry = device
        else:
            robot = coordinator.data.robots.get(serial)
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"robot_{serial}")},
                name=robot.name if robot else serial,
                manufacturer="Whisker",
            )

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
