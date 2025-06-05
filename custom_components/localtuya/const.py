"""Constants for localtuya integration."""

from dataclasses import dataclass
from typing import Any
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_ENTITIES,
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_ID,
    CONF_SCAN_INTERVAL,
    EntityCategory,
    Platform,
)

DOMAIN = "localtuya"
DATA_DISCOVERY = "discovery"

# Order on priority
SUPPORTED_PROTOCOL_VERSIONS = ["3.3", "3.1", "3.2", "3.4", "3.5"]


# Platforms in this list must support config flows
PLATFORMS = {
    "Alarm Control Panel": Platform.ALARM_CONTROL_PANEL,
    "Binary Sensor": Platform.BINARY_SENSOR,
    "Button": Platform.BUTTON,
    "Climate": Platform.CLIMATE,
    "Cover": Platform.COVER,
    "Fan": Platform.FAN,
    "Humidifier": Platform.HUMIDIFIER,
    "Light": Platform.LIGHT,
    "Lock": Platform.LOCK,
    "Number": Platform.NUMBER,
    "Remote": Platform.REMOTE,
    "Select": Platform.SELECT,
    "Sensor": Platform.SENSOR,
    "Siren": Platform.SIREN,
    "Switch": Platform.SWITCH,
    "Vacuum": Platform.VACUUM,
    "Water Heater": Platform.WATER_HEATER,
}

ATTR_CURRENT = "current"
ATTR_CURRENT_CONSUMPTION = "current_consumption"
ATTR_VOLTAGE = "voltage"
ATTR_UPDATED_AT = "updated_at"

# Tuya Devices
CONF_TUYA_IP = "ip"
CONF_TUYA_GWID = "gwId"
CONF_TUYA_VERSION = "version"

# Status Payloads.
RESTORE_STATES = {"0": "restore"}


# config flow
CONF_LOCAL_KEY = "local_key"
CONF_ENABLE_DEBUG = "enable_debug"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_NODE_ID = "node_id"
CONF_GATEWAY_ID = "gateway_id"
CONF_DPS_STRINGS = "dps_strings"
CONF_MODEL = "model"
CONF_PRODUCT_KEY = "product_key"
CONF_PRODUCT_NAME = "product_name"
CONF_USER_ID = "user_id"
CONF_ENABLE_ADD_ENTITIES = "add_entities"


CONF_ADD_DEVICE = "add_device"
CONF_EDIT_DEVICE = "edit_device"
CONF_CONFIGURE_CLOUD = "configure_cloud"
CONF_NO_CLOUD = "no_cloud"
CONF_MANUAL_DPS = "manual_dps_strings"
CONF_DEFAULT_VALUE = "dps_default_value"
CONF_RESET_DPIDS = "reset_dpids"
CONF_PASSIVE_ENTITY = "is_passive_entity"
CONF_DEVICE_SLEEP_TIME = "device_sleep_time"

# ALARM
CONF_ALARM_SUPPORTED_STATES = "alarm_supported_states"

# Binary_sensor, Siren
CONF_STATE_ON = "state_on"
CONF_RESET_TIMER = "reset_timer"

# light
CONF_BRIGHTNESS_LOWER = "brightness_lower"
CONF_BRIGHTNESS_UPPER = "brightness_upper"
CONF_COLOR = "color"
CONF_COLOR_MODE = "color_mode"
CONF_COLOR_MODE_SET = "color_mode_set"
CONF_COLOR_TEMP_MIN_KELVIN = "color_temp_min_kelvin"
CONF_COLOR_TEMP_MAX_KELVIN = "color_temp_max_kelvin"
CONF_COLOR_TEMP_REVERSE = "color_temp_reverse"
CONF_MUSIC_MODE = "music_mode"
CONF_SCENE_VALUES = "scene_values"
CONF_SCENE_VALUES_FRIENDLY = "scene_values_friendly"

# switch
CONF_CURRENT = "current"
CONF_CURRENT_CONSUMPTION = "current_consumption"
CONF_VOLTAGE = "voltage"

# cover
CONF_COMMANDS_SET = "commands_set"
CONF_POSITIONING_MODE = "positioning_mode"
CONF_CURRENT_POSITION_DP = "current_position_dp"
CONF_SET_POSITION_DP = "set_position_dp"
CONF_STOP_SWITCH_DP = "stop_switch_dp"
CONF_POSITION_INVERTED = "position_inverted"
CONF_SPAN_TIME = "span_time"

# fan
CONF_FAN_SPEED_CONTROL = "fan_speed_control"
CONF_FAN_OSCILLATING_CONTROL = "fan_oscillating_control"
CONF_FAN_SPEED_MIN = "fan_speed_min"
CONF_FAN_SPEED_MAX = "fan_speed_max"
CONF_FAN_ORDERED_LIST = "fan_speed_ordered_list"
CONF_FAN_DIRECTION = "fan_direction"
CONF_FAN_DIRECTION_FWD = "fan_direction_forward"
CONF_FAN_DIRECTION_REV = "fan_direction_reverse"
CONF_FAN_DPS_TYPE = "fan_dps_type"

# sensor
CONF_SCALING = "scaling"
CONF_STATE_CLASS = "state_class"

# climate
CONF_TARGET_TEMPERATURE_DP = "target_temperature_dp"
CONF_CURRENT_TEMPERATURE_DP = "current_temperature_dp"
CONF_TEMPERATURE_STEP = "temperature_step"
CONF_MIN_TEMP = "min_temperature"
CONF_MAX_TEMP = "max_temperature"
CONF_PRECISION = "precision"
CONF_TARGET_PRECISION = "target_precision"
CONF_HVAC_MODE_DP = "hvac_mode_dp"
CONF_HVAC_MODE_SET = "hvac_mode_set"
CONF_PRESET_DP = "preset_dp"
CONF_PRESET_SET = "preset_set"
CONF_HEURISTIC_ACTION = "heuristic_action"
CONF_HVAC_ACTION_DP = "hvac_action_dp"
CONF_HVAC_ACTION_SET = "hvac_action_set"
CONF_HVAC_ADD_OFF = "hvac_add_off"
CONF_ECO_DP = "eco_dp"
CONF_ECO_VALUE = "eco_value"
CONF_FAN_SPEED_LIST = "fan_speed_list"
CONF_SWING_MODE_DP = "swing_mode_dp"
CONF_SWING_MODES = "swing_modes"
CONF_SWING_HORIZONTAL_DP = "swing_horizontal_dp"
CONF_SWING_HORIZONTAL_MODES = "swing_horizontal_modes"

# vacuum
CONF_POWERGO_DP = "powergo_dp"
CONF_IDLE_STATUS_VALUE = "idle_status_value"
CONF_RETURNING_STATUS_VALUE = "returning_status_value"
CONF_DOCKED_STATUS_VALUE = "docked_status_value"
CONF_BATTERY_DP = "battery_dp"
CONF_MODE_DP = "mode_dp"
CONF_MODES = "modes"
CONF_FAN_SPEED_DP = "fan_speed_dp"
CONF_FAN_SPEEDS = "fan_speeds"
CONF_CLEAN_TIME_DP = "clean_time_dp"
CONF_CLEAN_AREA_DP = "clean_area_dp"
CONF_CLEAN_RECORD_DP = "clean_record_dp"
CONF_LOCATE_DP = "locate_dp"
CONF_FAULT_DP = "fault_dp"
CONF_PAUSED_STATE = "paused_state"
CONF_RETURN_MODE = "return_mode"
CONF_STOP_STATUS = "stop_status"
CONF_PAUSE_DP = "pause_dp"

# number
CONF_MIN_VALUE = "min_value"
CONF_MAX_VALUE = "max_value"
CONF_STEPSIZE = "step_size"

# select
CONF_OPTIONS = "select_options"
CONF_OPTIONS_FRIENDLY = "select_options_friendly"

# Remote
CONF_RECEIVE_DP = "receive_dp"
CONF_KEY_STUDY_DP = "key_study_dp"

# Lock
CONF_JAMMED_DP = "jammed_dp"
CONF_LOCK_STATE_DP = "lock_state_dp"

# Humidifier
CONF_HUMIDIFIER_SET_HUMIDITY_DP = "humidifier_set_humidity_dp"
CONF_HUMIDIFIER_CURRENT_HUMIDITY_DP = "humidifier_current_humidity_dp"
CONF_HUMIDIFIER_MODE_DP = "humidifier_mode_dp"
CONF_HUMIDIFIER_AVAILABLE_MODES = "humidifier_available_modes"

# Water Heater
CONF_TARGET_TEMPERATURE_LOW_DP = "target_temperature_low_dp"
CONF_TARGET_TEMPERATURE_HIGH_DP = "target_temperature_high_dp"

# States
ATTR_STATE = "raw_state"
CONF_RESTORE_ON_RECONNECT = "restore_on_reconnect"

# Categories
ENTITY_CATEGORY = {
    "None": None,
    "Configuration": EntityCategory.CONFIG,
    "Diagnostic": EntityCategory.DIAGNOSTIC,
}

# Default Categories
DEFAULT_CATEGORIES = {
    "CONTROL": ["switch", "climate", "fan", "vacuum", "light"],
    "CONFIG": ["select", "number", "button"],
    "DIAGNOSTIC": ["sensor", "binary_sensor"],
}


@dataclass
class DictSelector:
    """
    A class that manages the mapping between Tuya values and Home Assistant (HA) values.

    Attributes:
        tuya_ha (dict): A dictionary mapping Tuya values (keys) to HA values (values).
        reverse (bool): Swaps `tuya_ha` keys and values.
    """

    tuya_ha: dict[str, Any]
    reverse: bool = False

    def __post_init__(self):
        if self.reverse:
            self.tuya_ha = {v: k for k, v in self.tuya_ha.items()}

    @property
    def as_dict(self):
        """Return options as dict."""
        return self.tuya_ha

    @property
    def values(self) -> list:
        """Return options Tuya keys."""
        return getattr(self, "_cached_keys__tuya_ha", list(self.tuya_ha.keys()))

    @property
    def names(self) -> list:
        """Return options HA values."""
        return getattr(self, "_cached_values_tuya_ha", list(self.tuya_ha.values()))

    def to_ha(self, value: str, default=None):
        """Return the friendly name."""
        return self.tuya_ha.get(value, default)

    def to_tuya(self, name: str):
        """Return the tuya value."""
        reversed_dict = getattr(
            self, "_cached_reverse_tuya_ha", {v: k for k, v in self.tuya_ha.items()}
        )
        return reversed_dict.get(name)

    def __repr__(self) -> str:
        return "valid" if self.tuya_ha else ""


@dataclass
class DeviceConfig:
    """Represent the main configuration for LocalTuya device."""

    device_config: dict[str, Any]

    def __post_init__(self) -> None:
        self.id: str = self.device_config[CONF_DEVICE_ID]
        self.host: str = self.device_config[CONF_HOST]
        self.local_key: str = self.device_config[CONF_LOCAL_KEY]
        self.entities: list = self.device_config[CONF_ENTITIES]
        self.protocol_version: str = self.device_config[CONF_PROTOCOL_VERSION]
        self.sleep_time: int = self.device_config.get(CONF_DEVICE_SLEEP_TIME, 0)
        self.scan_interval: int = self.device_config.get(CONF_SCAN_INTERVAL, 0)
        self.enable_debug: bool = self.device_config.get(CONF_ENABLE_DEBUG, False)
        self.name: str = self.device_config.get(CONF_FRIENDLY_NAME)
        self.node_id: str | None = self.device_config.get(CONF_NODE_ID)
        self.model: str = self.device_config.get(CONF_MODEL, "Tuya generic")
        self.reset_dps: str = self.device_config.get(CONF_RESET_DPIDS, "")
        self.manual_dps: str = self.device_config.get(CONF_MANUAL_DPS, "")
        self.dps_strings: list = self.device_config.get(CONF_DPS_STRINGS, [])

    def as_dict(self):
        return self.device_config
