"""Support for Tesla covers."""
import logging

from teslajsonpy.car import TeslaCar

from homeassistant.components.cover import (
    CoverEntity,
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant

from . import TeslaDataUpdateCoordinator
from .base import TeslaCarEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the Tesla locks by config_entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    cars = hass.data[DOMAIN][config_entry.entry_id]["cars"]
    entities = []

    for car in cars.values():
        entities.append(TeslaCarChargerDoor(hass, car, coordinator))
        entities.append(TeslaCarFrunk(hass, car, coordinator))
        entities.append(TeslaCarTrunk(hass, car, coordinator))

    async_add_entities(entities, True)


class TeslaCarChargerDoor(TeslaCarEntity, CoverEntity):
    """Representation of a Tesla car charger door cover."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize charger door cover entity."""
        super().__init__(hass, car, coordinator)
        self.type = "charger door"
        self._attr_device_class = CoverDeviceClass.DOOR
        self._attr_icon = "mdi:ev-plug-tesla"
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        )

    async def async_close_cover(self, **kwargs):
        """Send close cover command."""
        _LOGGER.debug("Closing cover: %s", self.name)
        await self._car.charge_port_door_close()
        await self.async_update_ha_state()

    async def async_open_cover(self, **kwargs):
        """Send open cover command."""
        _LOGGER.debug("Opening cover: %s", self.name)
        await self._car.charge_port_door_open()
        await self.async_update_ha_state()

    @property
    def is_closed(self):
        """Return True if charger door is closed."""
        return not self._car.is_charge_port_door_open


class TeslaCarFrunk(TeslaCarEntity, CoverEntity):
    """Representation of a Tesla car frunk lock."""

    def __init__(
        self, hass: HomeAssistant, car: dict, coordinator: TeslaDataUpdateCoordinator
    ) -> None:
        """Initialize frunk lock entity."""
        super().__init__(hass, car, coordinator)
        self.type = "frunk"
        self._attr_device_class = CoverDeviceClass.DOOR
        self._attr_icon = "mdi:car"

    async def async_close_cover(self, **kwargs):
        """Send close cover command."""
        _LOGGER.debug("Closing cover: %s", self.name)
        if self.is_closed is False:
            await self._car.toggle_frunk()
            await self.async_update_ha_state()        
        
    async def async_open_cover(self, **kwargs):
        """Send open cover command."""
        _LOGGER.debug("Opening cover: %s", self.name)
        if self.is_closed is True:
            await self._car.toggle_frunk()
            await self.async_update_ha_state()

    @property
    def is_closed(self):
        """Return True if frunk is closed."""
        return self._car.is_frunk_closed

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        # This check is for the trunk, need to find one for frunk
        if self._car.powered_lift_gate:
            return CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

        return CoverEntityFeature.OPEN


class TeslaCarTrunk(TeslaCarEntity, CoverEntity):
    """Representation of a Tesla car trunk cover."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize trunk cover entity."""
        super().__init__(hass, car, coordinator)
        self.type = "trunk"
        self._attr_device_class = CoverDeviceClass.DOOR
        self._attr_icon = "mdi:car-back"

    async def async_close_cover(self, **kwargs):
        """Send close cover command."""
        _LOGGER.debug("Closing cover: %s", self.name)
        if self.is_closed is False:
            await self._car.toggle_trunk()
            await self.async_update_ha_state()

    async def async_open_cover(self, **kwargs):
        """Send open cover command."""
        _LOGGER.debug("Opening cover: %s", self.name)
        if self.is_closed is True:
            await self._car.toggle_trunk()
            await self.async_update_ha_state()

    @property
    def is_closed(self):
        """Return True if trunk is closed."""
        return self._car.is_trunk_closed

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        if self._car.powered_lift_gate:
            return CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

        return CoverEntityFeature.OPEN
