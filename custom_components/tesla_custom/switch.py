"""Support for Tesla charger switches."""
from custom_components.tesla_custom.const import ICONS
import logging

from homeassistant.components.switch import SwitchEntity

from . import DOMAIN as TESLA_DOMAIN
from .tesla_device import TeslaDevice
from .helpers import wait_for_climate

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Tesla binary_sensors by config_entry."""
    coordinator = hass.data[TESLA_DOMAIN][config_entry.entry_id]["coordinator"]
    entities = []
    for device in hass.data[TESLA_DOMAIN][config_entry.entry_id]["devices"]["switch"]:
        if device.type == "charger switch":
            entities.append(ChargerSwitch(device, coordinator))
            entities.append(UpdateSwitch(device, coordinator))
        elif device.type == "maxrange switch":
            entities.append(RangeSwitch(device, coordinator))
        elif device.type == "sentry mode switch":
            entities.append(SentryModeSwitch(device, coordinator))
        elif device.type == "heated steering switch":
            entities.append(HeatedSteeringWheelSwitch(device, coordinator))
    async_add_entities(entities, True)


class HeatedSteeringWheelSwitch(TeslaDevice, SwitchEntity):
    """Representation of a Tesla Heated Steering Wheel switch."""

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Turn on Heating Steering Wheel: %s", self.name)

        vin = self.tesla_device.vin()
        await wait_for_climate(self.hass, self.config_entry_id, vin)

        await self.tesla_device.set_steering_wheel_heat(True)
        self.async_write_ha_state()

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Turn off Heating Steering Wheel: %s", self.name)
        await self.tesla_device.set_steering_wheel_heat(False)
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        return self.tesla_device.get_steering_wheel_heat()

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICONS.get("heated steering wheel")


class ChargerSwitch(TeslaDevice, SwitchEntity):
    """Representation of a Tesla charger switch."""

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Enable charging: %s", self.name)
        await self.tesla_device.start_charge()
        self.async_write_ha_state()

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Disable charging for: %s", self.name)
        await self.tesla_device.stop_charge()
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        if self.tesla_device.is_charging() is None:
            return None
        return self.tesla_device.is_charging()


class RangeSwitch(TeslaDevice, SwitchEntity):
    """Representation of a Tesla max range charging switch."""

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Enable max range charging: %s", self.name)
        await self.tesla_device.set_max()
        self.async_write_ha_state()

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Disable max range charging: %s", self.name)
        await self.tesla_device.set_standard()
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        if self.tesla_device.is_maxrange() is None:
            return None
        return bool(self.tesla_device.is_maxrange())


class UpdateSwitch(TeslaDevice, SwitchEntity):
    """Representation of a Tesla update switch. Described in UI as polling."""

    def __init__(self, tesla_device, coordinator):
        """Initialise the switch."""
        super().__init__(tesla_device, coordinator)
        self.controller = coordinator.controller

    @property
    def name(self):
        """Return the name of the device."""
        return super().name.replace("charger", "polling")

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICONS.get("update switch")

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return super().unique_id.replace("charger", "update")

    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Enable polling: %s %s", self.name, self.tesla_device.id())
        self.controller.set_updates(car_id=self.tesla_device.id(), value=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Disable polling: %s %s", self.name, self.tesla_device.id())
        self.controller.set_updates(car_id=self.tesla_device.id(), value=False)
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        if self.controller.get_updates(self.tesla_device.id()) is None:
            return None
        return bool(self.controller.get_updates(self.tesla_device.id()))


class SentryModeSwitch(TeslaDevice, SwitchEntity):
    """Representation of a Tesla sentry mode switch."""

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Enable sentry mode: %s", self.name)
        await self.tesla_device.enable_sentry_mode()
        self.async_write_ha_state()

    @TeslaDevice.Decorators.check_for_reauth
    async def async_turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Disable sentry mode: %s", self.name)
        await self.tesla_device.disable_sentry_mode()
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        if self.tesla_device.is_on() is None:
            return None
        return self.tesla_device.is_on()
