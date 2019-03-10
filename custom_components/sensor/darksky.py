"""
Support for Dark Sky weather service.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.darksky/
"""
from datetime import timedelta
import logging

from requests.exceptions import (
    ConnectionError as ConnectError, HTTPError, Timeout)
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    ATTR_ATTRIBUTION, CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE,
    CONF_MONITORED_CONDITIONS, CONF_NAME, UNIT_UV_INDEX, CONF_UPDATE_INTERVAL,
    CONF_SCAN_INTERVAL, CONF_UPDATE_INTERVAL_INVALIDATION_VERSION)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

REQUIREMENTS = ['python-forecastio==1.4.0']

_LOGGER = logging.getLogger(__name__)

ATTRIBUTION = "Powered by Dark Sky"

CONF_FORECAST = 'forecast'
CONF_HOURLY_FORECAST = 'hourly_forecast'
CONF_LANGUAGE = 'language'
CONF_UNITS = 'units'

DEFAULT_LANGUAGE = 'en'
DEFAULT_NAME = 'Dark Sky'
SCAN_INTERVAL = timedelta(seconds=300)

DEPRECATED_SENSOR_TYPES = {
    'apparent_temperature_max',
    'apparent_temperature_min',
    'temperature_max',
    'temperature_min',
}

# Sensor types are defined like so:
# Name, si unit, us unit, ca unit, uk unit, uk2 unit
SENSOR_TYPES = {
    'summary': ['Summary', None, None, None, None, None, None,
                ['currently', 'hourly', 'daily']],
    'minutely_summary': ['Minutely Summary',
                         None, None, None, None, None, None, []],
    'hourly_summary': ['Hourly Summary', None, None, None, None, None, None,
                       []],
    'daily_summary': ['Daily Summary', None, None, None, None, None, None, []],
    'icon': ['Icon', None, None, None, None, None, None,
             ['currently', 'hourly', 'daily']],
    'nearest_storm_distance': ['Nearest Storm Distance',
                               'km', 'mi', 'km', 'km', 'mi',
                               'mdi:weather-lightning', ['currently']],
    'nearest_storm_bearing': ['Nearest Storm Bearing',
                              '°', '°', '°', '°', '°',
                              'mdi:weather-lightning', ['currently']],
    'precip_type': ['Precip', None, None, None, None, None,
                    'mdi:weather-pouring',
                    ['currently', 'minutely', 'hourly', 'daily']],
    'precip_intensity': ['Precip Intensity',
                         'mm/h', 'in', 'mm/h', 'mm/h', 'mm/h',
                         'mdi:weather-rainy',
                         ['currently', 'minutely', 'hourly', 'daily']],
    'precip_probability': ['Precip Probability',
                           '%', '%', '%', '%', '%', 'mdi:water-percent',
                           ['currently', 'minutely', 'hourly', 'daily']],
    'precip_accumulation': ['Precip Accumulation',
                            'cm', 'in', 'cm', 'cm', 'cm', 'mdi:weather-snowy',
                            ['hourly', 'daily']],
    'temperature': ['Temperature',
                    '°C', '°F', '°C', '°C', '°C', 'mdi:thermometer',
                    ['currently', 'hourly']],
    'apparent_temperature': ['Apparent Temperature',
                             '°C', '°F', '°C', '°C', '°C', 'mdi:thermometer',
                             ['currently', 'hourly']],
    'dew_point': ['Dew Point', '°C', '°F', '°C', '°C', '°C',
                  'mdi:thermometer', ['currently', 'hourly', 'daily']],
    'wind_speed': ['Wind Speed', 'm/s', 'mph', 'km/h', 'mph', 'mph',
                   'mdi:weather-windy', ['currently', 'hourly', 'daily']],
    'wind_bearing': ['Wind Bearing', '°', '°', '°', '°', '°', 'mdi:compass',
                     ['currently', 'hourly', 'daily']],
    'wind_gust': ['Wind Gust', 'm/s', 'mph', 'km/h', 'mph', 'mph',
                  'mdi:weather-windy-variant',
                  ['currently', 'hourly', 'daily']],
    'cloud_cover': ['Cloud Coverage', '%', '%', '%', '%', '%',
                    'mdi:weather-partlycloudy',
                    ['currently', 'hourly', 'daily']],
    'humidity': ['Humidity', '%', '%', '%', '%', '%', 'mdi:water-percent',
                 ['currently', 'hourly', 'daily']],
    'pressure': ['Pressure', 'mbar', 'mbar', 'mbar', 'mbar', 'mbar',
                 'mdi:gauge', ['currently', 'hourly', 'daily']],
    'visibility': ['Visibility', 'km', 'mi', 'km', 'km', 'mi', 'mdi:eye',
                   ['currently', 'hourly', 'daily']],
    'ozone': ['Ozone', 'DU', 'DU', 'DU', 'DU', 'DU', 'mdi:eye',
              ['currently', 'hourly', 'daily']],
    'apparent_temperature_max': ['Daily High Apparent Temperature',
                                 '°C', '°F', '°C', '°C', '°C',
                                 'mdi:thermometer', ['daily']],
    'apparent_temperature_high': ["Daytime High Apparent Temperature",
                                  '°C', '°F', '°C', '°C', '°C',
                                  'mdi:thermometer', ['daily']],
    'apparent_temperature_min': ['Daily Low Apparent Temperature',
                                 '°C', '°F', '°C', '°C', '°C',
                                 'mdi:thermometer', ['daily']],
    'apparent_temperature_low': ['Overnight Low Apparent Temperature',
                                 '°C', '°F', '°C', '°C', '°C',
                                 'mdi:thermometer', ['daily']],
    'temperature_max': ['Daily High Temperature',
                        '°C', '°F', '°C', '°C', '°C', 'mdi:thermometer',
                        ['daily']],
    'temperature_high': ['Daytime High Temperature',
                         '°C', '°F', '°C', '°C', '°C', 'mdi:thermometer',
                         ['daily']],
    'temperature_min': ['Daily Low Temperature',
                        '°C', '°F', '°C', '°C', '°C', 'mdi:thermometer',
                        ['daily']],
    'temperature_low': ['Overnight Low Temperature',
                        '°C', '°F', '°C', '°C', '°C', 'mdi:thermometer',
                        ['daily']],
    'precip_intensity_max': ['Daily Max Precip Intensity',
                             'mm/h', 'in', 'mm/h', 'mm/h', 'mm/h',
                             'mdi:thermometer', ['daily']],
    'uv_index': ['UV Index',
                 UNIT_UV_INDEX, UNIT_UV_INDEX, UNIT_UV_INDEX,
                 UNIT_UV_INDEX, UNIT_UV_INDEX, 'mdi:weather-sunny',
                 ['currently', 'hourly', 'daily']],
    'moon_phase': ['Moon Phase', None, None, None, None, None,
                   'mdi:weather-night', ['daily']],
    'sunrise_time': ['Sunrise', None, None, None, None, None,
                     'mdi:white-balance-sunny', ['daily']],
    'sunset_time': ['Sunset', None, None, None, None, None,
                    'mdi:weather-night', ['daily']],
    'alerts': ['Alerts', None, None, None, None, None,
                    'mdi:alert-circle-outline', []]
}

CONDITION_PICTURES = {
    'clear-day': ['/static/images/darksky/weather-sunny.svg',
                  'mdi:weather-sunny'],
    'clear-night': ['/static/images/darksky/weather-night.svg',
                    'mdi:weather-sunny'],
    'rain': ['/static/images/darksky/weather-pouring.svg',
             'mdi:weather-pouring'],
    'snow': ['/static/images/darksky/weather-snowy.svg',
             'mdi:weather-snowy'],
    'sleet': ['/static/images/darksky/weather-hail.svg',
              'mdi:weather-snowy-rainy'],
    'wind': ['/static/images/darksky/weather-windy.svg',
             'mdi:weather-windy'],
    'fog': ['/static/images/darksky/weather-fog.svg',
            'mdi:weather-fog'],
    'cloudy': ['/static/images/darksky/weather-cloudy.svg',
               'mdi:weather-cloudy'],
    'partly-cloudy-day': ['/static/images/darksky/weather-partlycloudy.svg',
                          'mdi:weather-partlycloudy'],
    'partly-cloudy-night': ['/static/images/darksky/weather-cloudy.svg',
                            'mdi:weather-partlycloudy'],
}

# Language Supported Codes
LANGUAGE_CODES = [
    'ar', 'az', 'be', 'bg', 'bs', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es',
    'et', 'fi', 'fr', 'he', 'hr', 'hu', 'id', 'is', 'it', 'ja', 'ka', 'ko',
    'kw', 'lv', 'nb', 'nl', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sr', 'sv',
    'tet', 'tr', 'uk', 'x-pig-latin', 'zh', 'zh-tw',
]

ALLOWED_UNITS = ['auto', 'si', 'us', 'ca', 'uk', 'uk2']

# Alert Attributes
ALERTS_ATTRS = [
    'time',
    'description',
    'expires',
    'severity',
    'uri',
    'regions',
    'title'
]

PLATFORM_SCHEMA = vol.All(
    PLATFORM_SCHEMA.extend({
        vol.Required(CONF_MONITORED_CONDITIONS):
            vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
        vol.Required(CONF_API_KEY): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_UNITS): vol.In(ALLOWED_UNITS),
        vol.Optional(CONF_LANGUAGE,
                     default=DEFAULT_LANGUAGE): vol.In(LANGUAGE_CODES),
        vol.Inclusive(
            CONF_LATITUDE,
            'coordinates',
            'Latitude and longitude must exist together'
        ): cv.latitude,
        vol.Inclusive(
            CONF_LONGITUDE,
            'coordinates',
            'Latitude and longitude must exist together'
        ): cv.longitude,
        vol.Optional(CONF_UPDATE_INTERVAL):
            vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(CONF_FORECAST):
            vol.All(cv.ensure_list, [vol.Range(min=0, max=7)]),
        vol.Optional(CONF_HOURLY_FORECAST):
            vol.All(cv.ensure_list, [vol.Range(min=0, max=48)]),
    }),
    cv.deprecated(
        CONF_UPDATE_INTERVAL,
        replacement_key=CONF_SCAN_INTERVAL,
        invalidation_version=CONF_UPDATE_INTERVAL_INVALIDATION_VERSION,
        default=SCAN_INTERVAL
    )
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Dark Sky sensor."""
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)
    language = config.get(CONF_LANGUAGE)
    interval = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)

    if CONF_UNITS in config:
        units = config[CONF_UNITS]
    elif hass.config.units.is_metric:
        units = 'si'
    else:
        units = 'us'

    forecast_data = DarkSkyData(
        api_key=config.get(CONF_API_KEY, None), latitude=latitude,
        longitude=longitude, units=units, language=language, interval=interval)
    forecast_data.update()
    forecast_data.update_currently()

    # If connection failed don't setup platform.
    if forecast_data.data is None:
        return

    name = config.get(CONF_NAME)

    forecast = config.get(CONF_FORECAST)
    forecast_hour = config.get(CONF_HOURLY_FORECAST)
    sensors = []
    for variable in config[CONF_MONITORED_CONDITIONS]:
        if variable in DEPRECATED_SENSOR_TYPES:
            _LOGGER.warning("Monitored condition %s is deprecated", variable)
        if (not SENSOR_TYPES[variable][7] or
                'currently' in SENSOR_TYPES[variable][7]):
            if not 'alerts' in variable:
                sensors.append(DarkSkySensor(forecast_data, variable, name))
            else:
                sensors.append(DarkSkyAlertSensor(forecast_data, variable, name))
        if forecast is not None and 'daily' in SENSOR_TYPES[variable][7]:
            for forecast_day in forecast:
                sensors.append(DarkSkySensor(
                    forecast_data, variable, name, forecast_day=forecast_day))
        if forecast_hour is not None and 'hourly' in SENSOR_TYPES[variable][7]:
            for forecast_h in forecast_hour:
                sensors.append(DarkSkySensor(
                    forecast_data, variable, name, forecast_hour=forecast_h))

    add_entities(sensors, True)


class DarkSkySensor(Entity):
    """Implementation of a Dark Sky sensor."""

    def __init__(self, forecast_data, sensor_type, name,
                 forecast_day=None, forecast_hour=None):
        """Initialize the sensor."""
        self.client_name = name
        self._name = SENSOR_TYPES[sensor_type][0]
        self.forecast_data = forecast_data
        self.type = sensor_type
        self.forecast_day = forecast_day
        self.forecast_hour = forecast_hour
        self._state = None
        self._icon = None
        self._unit_of_measurement = None

    @property
    def name(self):
        """Return the name of the sensor."""
        if self.forecast_day is not None:
            return '{} {} {}d'.format(
                self.client_name, self._name, self.forecast_day)
        if self.forecast_hour is not None:
            return '{} {} {}h'.format(
                self.client_name, self._name, self.forecast_hour)
        return '{} {}'.format(
            self.client_name, self._name)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def unit_system(self):
        """Return the unit system of this entity."""
        return self.forecast_data.unit_system

    @property
    def entity_picture(self):
        """Return the entity picture to use in the frontend, if any."""
        if self._icon is None or 'summary' not in self.type:
            return None

        if self._icon in CONDITION_PICTURES:
            return CONDITION_PICTURES[self._icon][0]

        return None

    def update_unit_of_measurement(self):
        """Update units based on unit system."""
        unit_index = {
            'si': 1,
            'us': 2,
            'ca': 3,
            'uk': 4,
            'uk2': 5
        }.get(self.unit_system, 1)
        self._unit_of_measurement = SENSOR_TYPES[self.type][unit_index]

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        if 'summary' in self.type and self._icon in CONDITION_PICTURES:
            return CONDITION_PICTURES[self._icon][1]

        return SENSOR_TYPES[self.type][6]

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    def update(self):
        """Get the latest data from Dark Sky and updates the states."""
        # Call the API for new forecast data. Each sensor will re-trigger this
        # same exact call, but that's fine. We cache results for a short period
        # of time to prevent hitting API limits. Note that Dark Sky will
        # charge users for too many calls in 1 day, so take care when updating.
        self.forecast_data.update()
        self.update_unit_of_measurement()

        if self.type == 'minutely_summary':
            self.forecast_data.update_minutely()
            minutely = self.forecast_data.data_minutely
            self._state = getattr(minutely, 'summary', '')
            self._icon = getattr(minutely, 'icon', '')
        elif self.type == 'hourly_summary':
            self.forecast_data.update_hourly()
            hourly = self.forecast_data.data_hourly
            self._state = getattr(hourly, 'summary', '')
            self._icon = getattr(hourly, 'icon', '')
        elif self.forecast_hour is not None:
            self.forecast_data.update_hourly()
            hourly = self.forecast_data.data_hourly
            if hasattr(hourly, 'data'):
                self._state = self.get_state(hourly.data[self.forecast_hour])
            else:
                self._state = 0
        elif self.type == 'daily_summary':
            self.forecast_data.update_daily()
            daily = self.forecast_data.data_daily
            self._state = getattr(daily, 'summary', '')
            self._icon = getattr(daily, 'icon', '')
        elif self.forecast_day is not None:
            self.forecast_data.update_daily()
            daily = self.forecast_data.data_daily
            if hasattr(daily, 'data'):
                self._state = self.get_state(daily.data[self.forecast_day])
            else:
                self._state = 0
        else:
            self.forecast_data.update_currently()
            currently = self.forecast_data.data_currently
            self._state = self.get_state(currently)

    def get_state(self, data):
        """
        Return a new state based on the type.

        If the sensor type is unknown, the current state is returned.
        """
        lookup_type = convert_to_camel(self.type)
        state = getattr(data, lookup_type, None)

        if state is None:
            return state

        if 'summary' in self.type:
            self._icon = getattr(data, 'icon', '')

        # Some state data needs to be rounded to whole values or converted to
        # percentages
        if self.type in ['precip_probability', 'cloud_cover', 'humidity']:
            return round(state * 100, 1)

        if self.type in ['dew_point', 'temperature', 'apparent_temperature',
                         'temperature_low', 'apparent_temperature_low',
                         'temperature_min', 'apparent_temperature_min',
                         'temperature_high', 'apparent_temperature_high',
                         'temperature_max', 'apparent_temperature_max'
                         'precip_accumulation', 'pressure', 'ozone',
                         'uvIndex']:
            return round(state, 1)
        return state

class DarkSkyAlertSensor(Entity):
    """Implementation of a Dark Sky sensor."""

    def __init__(self, forecast_data, sensor_type, name):
        """Initialize the sensor."""
        self.client_name = name
        self._name = SENSOR_TYPES[sensor_type][0]
        self.forecast_data = forecast_data
        self.type = sensor_type
        self._state = None
        self._icon = None
        self._alerts = {ATTR_ATTRIBUTION: ATTRIBUTION}

    @property
    def name(self):
        """Return the name of the sensor."""
        return '{} {}'.format(
            self.client_name, self._name)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        if self._state is not None and self._state > 0:
            return "mdi:alert-circle-outline"
        return "mdi:alert-circle-outline"

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._alerts

    def update(self):
        """Get the latest data from Dark Sky and updates the states."""
        # Call the API for new forecast data. Each sensor will re-trigger this
        # same exact call, but that's fine. We cache results for a short period
        # of time to prevent hitting API limits. Note that Dark Sky will
        # charge users for too many calls in 1 day, so take care when updating.
        self.forecast_data.update()

        if self.type == 'alerts':
            self.forecast_data.update_alerts()
            alerts = self.forecast_data.data_alerts
            self._state = self.get_state(alerts)

    def get_state(self, data):
        """
        Return a new state based on the type.

        If the sensor type is unknown, the current state is returned.
        """
        alerts = {}
        if data is None:
            self._alerts = alerts
            return data

        i = 0
        multiple_alerts = len(data) > 1
        for alert in data:
            for attr in ALERTS_ATTRS:
                if multiple_alerts:
                    dkey = attr + '_' + str(i)
                else:
                    dkey = attr
                alerts[dkey] = getattr(alert, attr)
            i += 1
        self._alerts = alerts

        return len(data)

def convert_to_camel(data):
    """
    Convert snake case (foo_bar_bat) to camel case (fooBarBat).

    This is not pythonic, but needed for certain situations.
    """
    components = data.split('_')
    return components[0] + "".join(x.title() for x in components[1:])


class DarkSkyData:
    """Get the latest data from Darksky."""

    def __init__(
            self, api_key, latitude, longitude, units, language, interval):
        """Initialize the data object."""
        self._api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.units = units
        self.language = language

        self.data = None
        self.unit_system = None
        self.data_currently = None
        self.data_minutely = None
        self.data_hourly = None
        self.data_daily = None
        self.data_alerts = None

        # Apply throttling to methods using configured interval
        self.update = Throttle(interval)(self._update)
        self.update_currently = Throttle(interval)(self._update_currently)
        self.update_minutely = Throttle(interval)(self._update_minutely)
        self.update_hourly = Throttle(interval)(self._update_hourly)
        self.update_daily = Throttle(interval)(self._update_daily)
        self.update_alerts = Throttle(interval)(self._update_alerts)

    def _update(self):
        """Get the latest data from Dark Sky."""
        import forecastio

        try:
            self.data = forecastio.load_forecast(
                self._api_key, self.latitude, self.longitude, units=self.units,
                lang=self.language)
        except (ConnectError, HTTPError, Timeout, ValueError) as error:
            _LOGGER.error("Unable to connect to Dark Sky: %s", error)
            self.data = None
        self.unit_system = self.data and self.data.json['flags']['units']

    def _update_currently(self):
        """Update currently data."""
        self.data_currently = self.data and self.data.currently()

    def _update_minutely(self):
        """Update minutely data."""
        self.data_minutely = self.data and self.data.minutely()

    def _update_hourly(self):
        """Update hourly data."""
        self.data_hourly = self.data and self.data.hourly()

    def _update_daily(self):
        """Update daily data."""
        self.data_daily = self.data and self.data.daily()

    def _update_alerts(self):
        """Update alerts data."""
        self.data_alerts = self.data and self.data.alerts()