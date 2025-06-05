"""Expose SomaFM as a media source."""
from __future__ import annotations

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, LOGGER
from .somafm import SomaFM, Station


async def async_get_media_source(hass: HomeAssistant) -> SomaFMMediaSource:
    """Set up SomaFM media source."""
    # SomaFM supports only a single config entry
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    return SomaFMMediaSource(hass, entry)


class SomaFMMediaSource(MediaSource):
    """Provide SomaFM stations as media sources."""

    name = "SomaFM"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize SomaFMMediaSource."""
        super().__init__(DOMAIN)
        self.hass = hass
        self.entry = entry

    @property
    def somafm(self) -> SomaFM | None:
        """Return the SomaFM service."""
        return self.hass.data.get(DOMAIN)

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve selected SomaFM station to a streaming URL."""
        somafm = self.somafm

        if somafm is None:
            raise Unresolvable("SomaFM not initialized")

        stations = await somafm.stations()
        for s in stations:
            if s.name == item.identifier:
                addr = await somafm.stream_url(s)
                return PlayMedia(addr, s.mime_type)

        raise Unresolvable("Radio station is no longer available")


    async def async_browse_media(
        self,
        item: MediaSourceItem,
    ) -> BrowseMediaSource:
        """Return media."""
        somafm = self.somafm

        if somafm is None:
            raise BrowseError("SomaFM not initialized")

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.CHANNEL,
            media_content_type=MediaType.MUSIC,
            thumbnail="https://somafm.com/apple-touch-icon.png",
            title=self.entry.title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                *await self._async_build_by_name(somafm, item),
                *await self._async_build_by_genre(somafm, item),
                *await self._async_build_by_popularity(somafm, item),
            ],
        )

    def build_stations(
        self, somafm: SomaFM, stations: list[Station]
    ) -> list[BrowseMediaSource]:
        """Build list of media sources from radio stations."""
        items: list[BrowseMediaSource] = []

        for station in stations:
            items.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=station.name,
                    media_class=MediaClass.MUSIC,
                    media_content_type=station.mime_type,
                    title=station.title,
                    can_play=True,
                    can_expand=False,
                    thumbnail=station.image,
                )
            )

        return items

    async def _async_build_by_name(
        self, somafm: SomaFM, item: MediaSourceItem
    ) -> list[BrowseMediaSource]:
        """Handle browsing radio stations by name."""
        if item.identifier == "name":
            stations = await somafm.stations()
            stations.sort(key=lambda s: s.title.lower())
            return self.build_stations(somafm, stations)
        if not item.identifier:
            return [
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier="name",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    title="A-Z",
                    can_play=False,
                    can_expand=True,
                )
            ]
        return []

    async def _async_build_by_genre(
        self, somafm: SomaFM, item: MediaSourceItem
    ) -> list[BrowseMediaSource]:
        """Handle browsing radio stations by genres."""
        category, _, tag = (item.identifier or "").partition("/")
        if category == "tag" and tag:
            stations = await somafm.stations()
            stations = [s for s in stations if tag in s.genres]
            return self.build_stations(somafm, stations)

        if category == "tag":
            genres = list(await somafm.genres())
            genres.sort()

            return [
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"tag/{tag}",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    title=tag.title(),
                    can_play=False,
                    can_expand=True,
                )
                for tag in genres
            ]

        if not item.identifier:
            return [
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier="tag",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    title="By Genre",
                    can_play=False,
                    can_expand=True,
                )
            ]
        return []

    async def _async_build_by_popularity(
        self, somafm: SomaFM, item: MediaSourceItem
    ) -> list[BrowseMediaSource]:
        """Handle browsing radio stations by popularity."""
        if not item.identifier:
            stations = await somafm.stations()
            stations.sort(key=lambda s: s.listeners, reverse=True)
            return self.build_stations(somafm, stations)
        return []
