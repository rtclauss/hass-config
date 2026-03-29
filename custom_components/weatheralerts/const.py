"""Constants for the local weatheralerts custom integration copy."""

DOMAIN = "weatheralerts"
VERSION = "2026.1.0"

CONF_ZONE = "zone"
CONF_COUNTY = "county"
CONF_ZONE_NAME = "zone_name"
CONF_NAME = "name"
CONF_ENTITY_NAME = "entity_name"
CONF_MARINE_ZONES = "marine_zones"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_API_TIMEOUT = "api_timeout"
CONF_DEDUPLICATE_ALERTS = "deduplicate_alerts"
CONF_EVENT_ICONS = "event_icons"
CONF_DEFAULT_ICON = "default_icon"

ALERTS_API = "https://api.weather.gov/alerts/active?zone={}"
HEADERS = {
    "accept": "application/json",
    "user-agent": f"HomeAssistant_weatheralerts/{VERSION}",
}

DEFAULT_UPDATE_INTERVAL = 90
DEFAULT_API_TIMEOUT = 20
DEFAULT_DEDUPLICATE_ALERTS = False

DEFAULT_EVENT_ICON = "hass:alert-rhombus"
DEFAULT_EVENT_ICONS = {
    "Air Quality Alert": "hass:blur",
    "Blizzard Warning": "hass:snowflake-alert",
    "Dense Fog Advisory": "hass:weather-fog",
    "Extreme Fire Danger": "hass:fire-alert",
    "Flash Flood Warning": "hass:water-alert",
    "Flood Warning": "hass:water-alert",
    "Freeze Warning": "hass:thermometer-minus",
    "Hazardous Weather Outlook": "hass:message-alert",
    "Heat Advisory": "hass:thermometer-plus",
    "High Wind Warning": "hass:weather-windy",
    "Severe Thunderstorm Warning": "hass:weather-lightning",
    "Special Weather Statement": "hass:message-alert",
    "Tornado Warning": "hass:weather-tornado",
    "Winter Storm Warning": "hass:snowflake-alert",
    "Winter Weather Advisory": "hass:snowflake-alert",
}
