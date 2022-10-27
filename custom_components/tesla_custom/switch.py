"""Support for Tesla switches."""
import logging

from teslajsonpy.car import TeslaCar

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from . import TeslaDataUpdateCoordinator
from .base import TeslaCarEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the Tesla switches by config_entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    cars = hass.data[DOMAIN][config_entry.entry_id]["cars"]
    entities = []

    for car in cars.values():
        if car.steering_wheel_heater:
            entities.append(TeslaCarHeatedSteeringWheel(hass, car, coordinator))
        if car.sentry_mode_available:
            entities.append(TeslaCarSentryMode(hass, car, coordinator))
        entities.append(TeslaCarPolling(hass, car, coordinator))
        entities.append(TeslaCarCharger(hass, car, coordinator))

    async_add_entities(entities, True)


class TeslaCarHeatedSteeringWheel(TeslaCarEntity, SwitchEntity):
    """Representation of a Tesla car heated steering wheel switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize heated steering wheel entity."""
        super().__init__(hass, car, coordinator)
        self.type = "heated steering"
        self._attr_icon = "mdi:steering"

    @property
    def is_on(self):
        """Return True if steering wheel heater is on."""
        return self._car.is_steering_wheel_heater_on

    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        await self._car.set_heated_steering_wheel(True)
        await self.async_update_ha_state()

    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        await self._car.set_heated_steering_wheel(False)
        await self.async_update_ha_state()


class TeslaCarPolling(TeslaCarEntity, SwitchEntity):
    """Representation of a polling switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize polling entity."""
        super().__init__(hass, car, coordinator)
        self.type = "polling"
        self._attr_icon = "mdi:car-connected"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        """Return True if updates available."""
        if self._coordinator.controller.get_updates(vin=self._car.vin) is None:
            return None

        return bool(self._coordinator.controller.get_updates(vin=self._car.vin))

    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Enable polling: %s %s", self.name, self._car.vin)
        self._coordinator.controller.set_updates(vin=self._car.vin, value=True)
        await self.async_update_ha_state()

    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Disable polling: %s %s", self.name, self._car.vin)
        self._coordinator.controller.set_updates(vin=self._car.vin, value=False)
        await self.async_update_ha_state()


class TeslaCarCharger(TeslaCarEntity, SwitchEntity):
    """Representation of a Tesla car charger switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize charger switch entity."""
        super().__init__(hass, car, coordinator)
        self.type = "charger"
        self._attr_icon = "mdi:ev-station"

    @property
    def is_on(self):
        """Return charging state."""
        return self._car.charging_state == "Charging"

    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        await self._car.start_charge()
        await self.async_update_ha_state()

    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        await self._car.stop_charge()
        await self.async_update_ha_state()


class TeslaCarSentryMode(TeslaCarEntity, SwitchEntity):
    """Representation of a Tesla car sentry mode switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize sentry mode entity."""
        super().__init__(hass, car, coordinator)
        self.type = "sentry mode"
        self._attr_icon = "mdi:shield-car"

    @property
    def is_on(self):
        """Return True if sentry mode is on."""
        sentry_mode_available = self._car.sentry_mode_available
        sentry_mode_status = self._car.sentry_mode

        if sentry_mode_available is True and sentry_mode_status is True:
            return True

        return False

    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        await self._car.set_sentry_mode(True)
        await self.async_update_ha_state()

    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        await self._car.set_sentry_mode(False)
        await self.async_update_ha_state()
