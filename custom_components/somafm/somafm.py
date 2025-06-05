"""SomaFM API."""
from __future__ import annotations

import asyncio
import socket
import json
import random
import re
import xml.etree.ElementTree as ET

import aiohttp

from .const import LOGGER

BASE_URL = "https://somafm.com"
RE_PLS = re.compile("File[0-9]*=(.*)")

class SomaFM:
    """SomaFM interface."""

    user_agent: str

    request_timeout: float = 8.0
    session: aiohttp.client.ClientSession | None = None

    _close_session: bool = False
    _stations: list[Station] | None = None

    def __init__(self, session, user_agent: str) -> None:
        """Initialize RadioMediaSource."""
        self.session = session
        self.user_agent = user_agent

    async def _request(self, url: str) -> str:
        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._close_session = True

        try:
            async with asyncio.timeout(self.request_timeout):
                response = await self.session.request(
                    "GET",
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                    },
                    raise_for_status=True,
                )

            content_type = response.headers.get("Content-Type", "")
            text = await response.text()
        except asyncio.TimeoutError as exception:
            msg = "Timeout occurred while connecting to the SomaFM API"
            raise SomaFMError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = "Error occurred while communicating with the SomaFM API"
            raise SomaFMError(msg) from exception

        return text

    async def stream_url(self, station: Station) -> str:
        """Return a random stream URL."""
        pls = await self._request(station.addr)
        matches = RE_PLS.findall(pls)
        return random.choice(matches)

    async def stations(self) -> list[Station]:
        """Return a list of Stations."""
        if not self._stations:
            text = await self._request(BASE_URL + "/channels.xml")
            self._stations = parse_stations(text)
            self._stations.sort(key=lambda s: s.title.lower())
        return self._stations

    async def genres(self) -> set[str]:
        """Return the genres of all stations."""
        stations = await self.stations()
        genres = set()
        for s in stations:
            for t in s.genres:
                genres.add(t)
        return genres

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()


def parse_stations(text: str) -> list[Station]:
    """Return the Stations in the somafm.com index HTML."""
    stations = []
    root = ET.fromstring(text)
    for chan in root:
        if chan.tag != "channel":
            continue
        name = chan.attrib["id"]
        title = chan.find("title").text
        genres = chan.find("genre").text.split("|")
        listeners = int(chan.find("listeners").text)
        image = chan.find("largeimage").text
        stream = chan.find("highestpls")
        addr = stream.text
        format = stream.get("format")
        stations.append(Station(name, title, image, genres, listeners, format, addr))
    return stations


class SomaFMError(Exception):
    """Custom error type."""

    msg: str


CODEC_TO_MIMETYPE = {
    "MP3": "audio/mpeg",
    "AAC": "audio/aac",
}


class Station:
    """A station's metadata."""

    name: str
    title: str
    image: str
    genres: list[str]
    listeners: int
    format: str
    addr: str
    mime_type: str

    def __init__(self, name, title, image, genres, listeners, format, addr) -> None:
        self.name = name
        self.title = title
        self.image = image
        self.genres = genres
        self.listeners = listeners
        self.format = format
        self.addr = addr
        self.mime_type = CODEC_TO_MIMETYPE[format.upper()]
