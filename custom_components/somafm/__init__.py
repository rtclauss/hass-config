"""The SomaFM integration."""
from __future__ import annotations

from aiodns.error import DNSError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .somafm import SomaFM, SomaFMError


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SomaFM from a config entry.

    This integration doesn't set up any entities, as it provides a media source
    only.
    """
    session = async_get_clientsession(hass)
    somafm = SomaFM(session=session, user_agent=f"HomeAssistant/{__version__}")

    try:
        await somafm.stations()
    except (DNSError, SomaFMError) as err:
        raise ConfigEntryNotReady("Could not connect to SomaFM API") from err

    hass.data[DOMAIN] = somafm
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    del hass.data[DOMAIN]
    return True
