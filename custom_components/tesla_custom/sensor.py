"""Support for the Tesla sensors."""
from teslajsonpy.car import TeslaCar
from teslajsonpy.const import RESOURCE_TYPE_SOLAR, RESOURCE_TYPE_BATTERY
from teslajsonpy.energy import EnergySite, PowerwallSite

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    ENERGY_KILO_WATT_HOUR,
    ENERGY_WATT_HOUR,
    LENGTH_KILOMETERS,
    LENGTH_MILES,
    PERCENTAGE,
    POWER_WATT,
    POWER_KILO_WATT,
    SPEED_MILES_PER_HOUR,
    TEMP_CELSIUS,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.util.unit_conversion import DistanceConverter

from . import TeslaDataUpdateCoordinator
from .base import TeslaCarEntity, TeslaEnergyEntity
from .const import DISTANCE_UNITS_KM_HR, DOMAIN

SOLAR_SITE_SENSORS = ["solar power", "grid power", "load power"]
BATTERY_SITE_SENSORS = SOLAR_SITE_SENSORS + ["battery power"]


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the Tesla Sensors by config_entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    cars = hass.data[DOMAIN][config_entry.entry_id]["cars"]
    energysites = hass.data[DOMAIN][config_entry.entry_id]["energysites"]
    entities = []

    for car in cars.values():
        entities.append(TeslaCarBattery(hass, car, coordinator))
        entities.append(TeslaCarChargerRate(hass, car, coordinator))
        entities.append(TeslaCarChargerEnergy(hass, car, coordinator))
        entities.append(TeslaCarChargerPower(hass, car, coordinator))
        entities.append(TeslaCarOdometer(hass, car, coordinator))
        entities.append(TeslaCarRange(hass, car, coordinator))
        entities.append(TeslaCarTemp(hass, car, coordinator))
        entities.append(TeslaCarTemp(hass, car, coordinator, inside=True))

    for energysite in energysites.values():
        if (
            energysite.resource_type == RESOURCE_TYPE_SOLAR
            and energysite.has_load_meter
        ):
            for sensor_type in SOLAR_SITE_SENSORS:
                entities.append(
                    TeslaEnergyPowerSensor(hass, energysite, coordinator, sensor_type)
                )
        elif energysite.resource_type == RESOURCE_TYPE_SOLAR:
            entities.append(
                TeslaEnergyPowerSensor(hass, energysite, coordinator, "solar power")
            )

        if energysite.resource_type == RESOURCE_TYPE_BATTERY:
            entities.append(TeslaEnergyBattery(hass, energysite, coordinator))
            entities.append(TeslaEnergyBatteryRemaining(hass, energysite, coordinator))
            entities.append(TeslaEnergyBackupReserve(hass, energysite, coordinator))
            for sensor_type in BATTERY_SITE_SENSORS:
                entities.append(
                    TeslaEnergyPowerSensor(hass, energysite, coordinator, sensor_type)
                )

    async_add_entities(entities, True)


class TeslaCarBattery(TeslaCarEntity, SensorEntity):
    """Representation of the Tesla car battery sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize the Sensor Entity."""
        super().__init__(hass, car, coordinator)
        self.type = "battery"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:battery"

    @staticmethod
    def has_battery() -> bool:
        """Return whether the device has a battery."""
        return True

    @property
    def native_value(self) -> int:
        """Return battery level."""
        return self._car.battery_level

    @property
    def icon(self):
        """Return icon for the battery."""
        charging = self._car.battery_level == "Charging"

        return icon_for_battery_level(
            battery_level=self.native_value, charging=charging
        )


class TeslaCarChargerEnergy(TeslaCarEntity, SensorEntity):
    """Representation of a Tesla car energy added sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize energy added entity."""
        super().__init__(hass, car, coordinator)
        self.type = "energy added"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = ENERGY_KILO_WATT_HOUR
        self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self) -> float:
        """Return the charge energy added."""
        if self._car.charging_state == "Charging":
            return self._car.charge_energy_added
        return "0"

    @property
    def extra_state_attributes(self):
        """Return device state attributes."""
        if self._car.charge_miles_added_rated:
            added_range = self._car.charge_miles_added_rated
        elif (
            self._car.charge_miles_added_ideal
            and self._car.gui_range_display == "Ideal"
        ):
            added_range = self._car.charge_miles_added_ideal
        else:
            added_range = 0

        if self._car.gui_distance_units == DISTANCE_UNITS_KM_HR:
            added_range = DistanceConverter.convert(
                added_range, LENGTH_MILES, LENGTH_KILOMETERS
            )

        return {
            "added_range": round(added_range, 2),
        }


class TeslaCarChargerPower(TeslaCarEntity, SensorEntity):
    """Representation of a Tesla car charger power."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize energy added entity."""
        super().__init__(hass, car, coordinator)
        self.type = "charger power"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = POWER_KILO_WATT

    @property
    def native_value(self) -> int:
        """Return the charger power."""
        return self._car.charger_power

    @property
    def extra_state_attributes(self):
        """Return device state attributes."""
        return {
            "charger_amps_request": self._car.charge_current_request,
            "charger_amps_actual": self._car.charger_actual_current,
            "charger_volts": self._car.charger_voltage,
            "charger_phases": self._car.charger_phases,
        }


class TeslaCarChargerRate(TeslaCarEntity, SensorEntity):
    """Representation of the Tesla car charging rate."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize charging rate entity."""
        super().__init__(hass, car, coordinator)
        self.type = "charging rate"
        self._attr_device_class = SensorDeviceClass.SPEED
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = SPEED_MILES_PER_HOUR
        self._attr_icon = "mdi:speedometer"

    @property
    def native_value(self) -> float:
        """Return charge rate."""
        charge_rate = self._car.charge_rate

        if charge_rate is None:
            return charge_rate

        return round(charge_rate, 2)

    @property
    def extra_state_attributes(self):
        """Return device state attributes."""
        return {
            "time_left": self._car.time_to_full_charge,
        }


class TeslaCarOdometer(TeslaCarEntity, SensorEntity):
    """Representation of the Tesla car odometer sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize odometer entity."""
        super().__init__(hass, car, coordinator)
        self.type = "odometer"
        self._attr_device_class = SensorDeviceClass.DISTANCE
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = LENGTH_MILES
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self) -> float:
        """Return the odometer."""
        odometer_value = self._car.odometer

        if odometer_value is None:
            return None

        return round(odometer_value, 2)


class TeslaCarRange(TeslaCarEntity, SensorEntity):
    """Representation of the Tesla car range sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize range entity."""
        super().__init__(hass, car, coordinator)
        self.type = "range"
        self._attr_device_class = SensorDeviceClass.DISTANCE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = LENGTH_MILES
        self._attr_icon = "mdi:gauge"

    @property
    def native_value(self) -> float:
        """Return range."""
        range_value = self._car.battery_range

        if self._car.gui_range_display == "Ideal":
            range_value = self._car.ideal_battery_range

        if range_value is None:
            return None

        return round(range_value, 2)


class TeslaCarTemp(TeslaCarEntity, SensorEntity):
    """Representation of a Tesla car temp sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        car: TeslaCar,
        coordinator: TeslaDataUpdateCoordinator,
        *,
        inside=False,
    ) -> None:
        """Initialize temp entity."""
        super().__init__(hass, car, coordinator)
        self.type = "temperature"
        self.inside = inside

        if inside is True:
            self.type += " (inside)"
        else:
            self.type += " (outside)"

        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = TEMP_CELSIUS
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self) -> float:
        """Return car temperature."""
        if self.inside is True:
            return self._car.inside_temp

        return self._car.outside_temp


class TeslaEnergyPowerSensor(TeslaEnergyEntity, SensorEntity):
    """Representation of a Tesla energy power sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        energysite: EnergySite,
        coordinator: TeslaDataUpdateCoordinator,
        sensor_type: str,
    ) -> None:
        """Initialize power sensor."""
        super().__init__(hass, energysite, coordinator)
        self.type = sensor_type
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = POWER_WATT

        if self.type == "solar power":
            self._attr_icon = "mdi:solar-power-variant"
        if self.type == "grid power":
            self._attr_icon = "mdi:transmission-tower"
        if self.type == "load power":
            self._attr_icon = "mdi:home-lightning-bolt"
        if self.type == "battery power":
            self._attr_icon = "mdi:home-battery"

    @property
    def native_value(self) -> float:
        """Return power in Watts."""
        if self.type == "solar power":
            return round(self._energysite.solar_power)
        if self.type == "grid power":
            return round(self._energysite.grid_power)
        if self.type == "load power":
            return round(self._energysite.load_power)
        if self.type == "battery power":
            return round(self._energysite.battery_power)


class TeslaEnergyBattery(TeslaEnergyEntity, SensorEntity):
    """Representation of the Tesla energy battery sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        energysite: PowerwallSite,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize battery sensor entity."""
        super().__init__(hass, energysite, coordinator)
        self.type = "battery"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @staticmethod
    def has_battery() -> bool:
        """Return whether the device has a battery."""
        return True

    @property
    def native_value(self) -> int:
        """Return battery level."""
        return round(self._energysite.percentage_charged)

    @property
    def icon(self):
        """Return icon for the battery."""
        charging = self._energysite.battery_power < -100

        return icon_for_battery_level(
            battery_level=self.native_value, charging=charging
        )


class TeslaEnergyBatteryRemaining(TeslaEnergyEntity, SensorEntity):
    """Representation of a Tesla energy battery remaining sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        energysite: PowerwallSite,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize battery remaining entity."""
        super().__init__(hass, energysite, coordinator)
        self.type = "battery remaining"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = ENERGY_WATT_HOUR

    @property
    def native_value(self) -> int:
        """Return battery energy remaining."""
        return round(self._energysite.energy_left)

    @property
    def icon(self):
        """Return icon for the battery remaining."""
        charging = self._energysite.battery_power < -100

        return icon_for_battery_level(
            battery_level=self._energysite.percentage_charged, charging=charging
        )


class TeslaEnergyBackupReserve(TeslaEnergyEntity, SensorEntity):
    """Representation of a Tesla energy backup reserve sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        energysite: PowerwallSite,
        coordinator: TeslaDataUpdateCoordinator,
    ) -> None:
        """Initialize backup energy reserve entity."""
        super().__init__(hass, energysite, coordinator)
        self.type = "backup reserve"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> int:
        """Return backup reserve level."""
        return round(self._energysite.backup_reserve_percent)

    @property
    def icon(self):
        """Return icon for the backup reserve."""
        return icon_for_battery_level(battery_level=self.native_value)
