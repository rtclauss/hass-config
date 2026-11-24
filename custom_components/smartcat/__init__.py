"""Smart Cat: Whisker+-style insights for Litter-Robots, computed locally."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DB_FILENAME, DOMAIN
from .coordinator import SmartCatConfigEntry, SmartCatCoordinator
from .core.store import Store
from .services import async_setup_services
from .whisker import get_account

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SmartCatConfigEntry) -> bool:
    """Set up Smart Cat from a config entry."""
    if get_account(hass) is None:
        raise ConfigEntryNotReady("Waiting for the Whisker (litterrobot) integration")

    store = await hass.async_add_executor_job(Store, hass.config.path(DB_FILENAME))
    coordinator = SmartCatCoordinator(hass, entry, store)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await hass.async_add_executor_job(store.close)
        raise
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: SmartCatConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SmartCatConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = entry.runtime_data
        coordinator.async_shutdown_listeners()
        await hass.async_add_executor_job(coordinator.store.close)
    return unloaded
