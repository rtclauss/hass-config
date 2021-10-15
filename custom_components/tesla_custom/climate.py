"""Support for Tesla HVAC system."""
from __future__ import annotations

import logging

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS, TEMP_FAHRENHEIT
from teslajsonpy.exceptions import UnknownPresetMode

from . import DOMAIN as TESLA_DOMAIN
from .tesla_device import TeslaDevice

_LOGGER = logging.getLogger(__name__)

SUPPORT_HVAC = [HVAC_MODE_HEAT_COOL, HVAC_MODE_OFF]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Tesla binary_sensors by config_entry."""
    async_add_entities(
        [
            TeslaThermostat(
                device,
                hass.data[TESLA_DOMAIN][config_entry.entry_id]["coordinator"],
            )
            for device in hass.data[TESLA_DOMAIN][config_entry.entry_id]["devices"][
                "climate"
            ]
        ],
        True,
    )


class TeslaThermostat(TeslaDevice, ClimateEntity):
    """Representation of a Tesla climate."""

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_PRESET_MODE

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        if self.tesla_device.is_hvac_enabled():
            return HVAC_MODE_HEAT_COOL
        return HVAC_MODE_OFF

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return SUPPORT_HVAC

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        if self.tesla_device.measurement == "F":
            return TEMP_FAHRENHEIT
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.tesla_device.get_current_temp()

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self.tesla_device.get_goal_temp()

    @TeslaDevice.Decorators.check_for_reauth
    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            _LOGGER.debug("%s: Setting temperature to %s", self.name, temperature)
            await self.tesla_device.set_temperature(temperature)

    @TeslaDevice.Decorators.check_for_reauth
    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug("%s: Setting hvac mode to %s", self.name, hvac_mode)
        if hvac_mode == HVAC_MODE_OFF:
            await self.tesla_device.set_status(False)
        elif hvac_mode == HVAC_MODE_HEAT_COOL:
            await self.tesla_device.set_status(True)

    @TeslaDevice.Decorators.check_for_reauth
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        _LOGGER.debug("%s: Setting preset_mode to: %s", self.name, preset_mode)
        try:
            await self.tesla_device.set_preset_mode(preset_mode)
        except UnknownPresetMode as ex:
            _LOGGER.error("%s", ex.message)

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode, e.g., home, away, temp.

        Requires SUPPORT_PRESET_MODE.
        """
        return self.tesla_device.preset_mode

    @property
    def preset_modes(self) -> list[str] | None:
        """Return a list of available preset modes.

        Requires SUPPORT_PRESET_MODE.
        """
        return self.tesla_device.preset_modes
