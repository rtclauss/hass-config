"""Support for tracking Tesla cars."""
from __future__ import annotations

from homeassistant.components.device_tracker import SOURCE_TYPE_GPS
from homeassistant.components.device_tracker.config_entry import TrackerEntity

from . import DOMAIN as TESLA_DOMAIN
from .tesla_device import TeslaDevice


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Tesla binary_sensors by config_entry."""
    entities = [
        TeslaDeviceEntity(
            device,
            hass.data[TESLA_DOMAIN][config_entry.entry_id]["coordinator"],
        )
        for device in hass.data[TESLA_DOMAIN][config_entry.entry_id]["devices"][
            "devices_tracker"
        ]
    ]
    async_add_entities(entities, True)


class TeslaDeviceEntity(TeslaDevice, TrackerEntity):
    """A class representing a Tesla device."""

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        location = self.tesla_device.get_location()
        return self.tesla_device.get_location().get("latitude") if location else None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        location = self.tesla_device.get_location()
        return self.tesla_device.get_location().get("longitude") if location else None

    @property
    def source_type(self):
        """Return the source type, eg gps or router, of the device."""
        return SOURCE_TYPE_GPS

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the device."""
        attr = super().extra_state_attributes.copy()
        location = self.tesla_device.get_location()
        if location:
            attr.update(
                {
                    "trackr_id": self.unique_id,
                    "heading": location["heading"],
                    "speed": location["speed"],
                }
            )
        return attr
