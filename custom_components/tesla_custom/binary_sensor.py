"""Support for Tesla binary sensors."""
import logging

from teslajsonpy.car import TeslaCar
from teslajsonpy.const import GRID_ACTIVE, RESOURCE_TYPE_BATTERY
from teslajsonpy.energy import PowerwallSite

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant

from . import TeslaDataUpdateCoordinator
from .base import TeslaCarEntity, TeslaEnergyEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the Tesla selects by config_entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    cars = hass.data[DOMAIN][config_entry.entry_id]["cars"]
    energysites = hass.data[DOMAIN][config_entry.entry_id]["energysites"]
    entities = []

    for car in cars.values():
        entities.append(TeslaCarParkingBrake(hass, car, coordinator))
        entities.append(TeslaCarOnline(hass, car, coordinator))
        entities.append(TeslaCarChargerConnection(hass, car, coordinator))
        entities.append(TeslaCarCharging(hass, car, coordinator))

    for energysite in energysites.values():
        if energysite.resource_type == RESOURCE_TYPE_BATTERY:
            entities.append(TeslaEnergyBatteryCharging(hass, energysite, coordinator))
            entities.append(TeslaEnergyGridStatus(hass, energysite, coordinator))

    async_add_entities(entities, True)


class TeslaCarParkingBrake(TeslaCarEntity, BinarySensorEntity):
    """Representation of a Tesla car parking brake binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize parking brake entity."""
        super().__init__(hass, car, coordinator)
        self.type = "parking brake"
        self._attr_icon = "mdi:car-brake-parking"
        self._attr_device_class = None

    @property
    def is_on(self):
        """Return True if car shift state in park or None."""
        # When car is parked and off, Tesla API reports shift_state None
        return self._car.shift_state == "P" or self._car.shift_state is None


class TeslaCarChargerConnection(TeslaCarEntity, BinarySensorEntity):
    """Representation of a Tesla car charger connection binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize charger connection entity."""
        super().__init__(hass, car, coordinator)
        self.type = "charger"
        self._attr_icon = "mdi:ev-station"
        self._attr_device_class = BinarySensorDeviceClass.PLUG

    @property
    def is_on(self):
        """Return True if charger connected."""
        return self._car.charging_state != "Disconnected"

    @property
    def extra_state_attributes(self):
        """Return device state attributes."""
        return {
            "charging_state": self._car.charging_state,
            "conn_charge_cable": self._car.conn_charge_cable,
            "fast_charger_present": self._car.fast_charger_present,
            "fast_charger_brand": self._car.fast_charger_brand,
            "fast_charger_type": self._car.fast_charger_type,
        }


class TeslaCarCharging(TeslaCarEntity, BinarySensorEntity):
    """Representation of Tesla car charging binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize charging entity."""
        super().__init__(hass, car, coordinator)
        self.type = "charging"
        self._attr_icon = "mdi:ev-station"
        self._attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        return self._car.charging_state == "Charging"


class TeslaCarOnline(TeslaCarEntity, BinarySensorEntity):
    """Representation of a Tesla car online binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize car online entity."""
        super().__init__(hass, car, coordinator)
        self.type = "online"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return True if car is online."""
        return self._car.is_on

    @property
    def extra_state_attributes(self):
        """Return device state attributes."""
        return {
            "vehicle_id": str(self._car.vehicle_id),
            "vin": self._car.vin,
            "id": str(self._car.id),
        }


class TeslaEnergyBatteryCharging(TeslaEnergyEntity, BinarySensorEntity):
    """Representation of a Tesla energy charging binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        energysite: PowerwallSite,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize battery charging entity."""
        super().__init__(hass, energysite, coordinator)
        self.type = "battery charging"
        self._attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
        self._attr_icon = "mdi:battery-charging"

    @property
    def is_on(self) -> bool:
        """Return True if battery charging."""
        return self._energysite.battery_power < -100


class TeslaEnergyGridStatus(TeslaEnergyEntity, BinarySensorEntity):
    """Representation of the Tesla energy grid status binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        energysite: PowerwallSite,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize grid status entity."""
        super().__init__(hass, energysite, coordinator)
        self.type = "grid status"
        self._attr_device_class = BinarySensorDeviceClass.POWER

    @property
    def is_on(self) -> bool:
        """Return True if grid status is active."""
        return self._energysite.grid_status == GRID_ACTIVE
