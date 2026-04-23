from __future__ import annotations

import binascii
import struct
import zlib

from .payload import DisplayPayload


WIDTH = 400
HEIGHT = 300

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (215, 0, 0)
YELLOW = (235, 190, 0)

ACCENT_COLORS = {
    "black": BLACK,
    "red": RED,
    "yellow": YELLOW,
}

LEVEL_COLORS = {
    "normal": BLACK,
    "emphasis": BLACK,
    "urgent": RED,
}


def render_payload(payload: DisplayPayload) -> bytes:
    canvas = Canvas(WIDTH, HEIGHT)
    accent = ACCENT_COLORS[payload.accent]

    canvas.rectangle(0, 0, WIDTH, 14, accent)
    canvas.text(
        18,
        30,
        payload.title or payload.mode.replace("_", " "),
        scale=4,
        color=BLACK,
    )
    if payload.subtitle:
        canvas.text(20, 75, payload.subtitle, scale=2, color=BLACK)

    y = 112
    for section in payload.sections:
        if section.get("type") != "rows":
            continue
        for row in section.get("rows", ()):
            level = row.get("level", "normal")
            row_color = LEVEL_COLORS.get(level, BLACK)
            if level in {"emphasis", "urgent"}:
                canvas.rectangle(18, y - 8, 382, y + 28, ACCENT_COLORS[payload.accent])
                row_color = WHITE if level == "urgent" else BLACK
            canvas.icon(26, y - 4, row.get("icon", ""), scale=2, color=row_color)
            canvas.text(56, y, row.get("label", ""), scale=2, color=row_color)
            canvas.text(170, y, row.get("value", ""), scale=2, color=row_color)
            y += 42

    if payload.footer:
        canvas.rectangle(0, HEIGHT - 30, WIDTH, HEIGHT, BLACK)
        canvas.text(18, HEIGHT - 22, payload.footer, scale=1, color=WHITE)

    return canvas.to_png()


class Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(WHITE * width * height)

    def rectangle(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        color: tuple[int, int, int],
    ) -> None:
        left = max(0, left)
        top = max(0, top)
        right = min(self.width, right)
        bottom = min(self.height, bottom)
        for y in range(top, bottom):
            for x in range(left, right):
                self._set_pixel(x, y, color)

    def text(
        self,
        left: int,
        top: int,
        text: str,
        scale: int,
        color: tuple[int, int, int],
    ) -> None:
        x = left
        max_x = self.width - 8
        for char in text.upper():
            glyph = FONT.get(char, FONT["?"])
            if x + 5 * scale > max_x:
                break
            self._glyph(x, top, glyph, scale, color)
            x += 6 * scale

    def icon(self, left: int, top: int, name: str, scale: int, color: tuple[int, int, int]) -> None:
        glyph = ICONS.get(name)
        if glyph is None:
            return
        self._glyph(left, top, glyph, scale, color)

    def to_png(self) -> bytes:
        raw = bytearray()
        row_width = self.width * 3
        for y in range(self.height):
            row_start = y * row_width
            raw.append(0)
            raw.extend(self.pixels[row_start : row_start + row_width])

        return (
            PNG_SIGNATURE
            + _chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0),
            )
            + _chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
            + _chunk(b"IEND", b"")
        )

    def _glyph(
        self,
        left: int,
        top: int,
        glyph: tuple[str, ...],
        scale: int,
        color: tuple[int, int, int],
    ) -> None:
        for gy, row in enumerate(glyph):
            for gx, value in enumerate(row):
                if value != "1":
                    continue
                self.rectangle(
                    left + gx * scale,
                    top + gy * scale,
                    left + (gx + 1) * scale,
                    top + (gy + 1) * scale,
                    color,
                )

    def _set_pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        index = (y * self.width + x) * 3
        self.pixels[index : index + 3] = bytes(color)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return (
        struct.pack(">I", len(data))
        + body
        + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
    )


FONT: dict[str, tuple[str, ...]] = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00001", "00001", "00001", "00001", "10001", "10001", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


ICONS: dict[str, tuple[str, ...]] = {
    "mdi:weather-sunny": (
        "0010000100",
        "0001001000",
        "1000000001",
        "0001111000",
        "0011111100",
        "0011111100",
        "0001111000",
        "1000000001",
        "0001001000",
        "0010000100",
    ),
    "mdi:weather-partly-cloudy": (
        "0000100000",
        "0010010000",
        "0001110000",
        "0011111000",
        "0001110010",
        "0011111111",
        "0111111111",
        "1111111110",
        "0111111100",
        "0000000000",
    ),
    "mdi:weather-cloudy": (
        "0000000000",
        "0001110000",
        "0011111000",
        "0111111100",
        "1111111110",
        "1111111111",
        "0111111111",
        "0011111110",
        "0000000000",
        "0000000000",
    ),
    "mdi:weather-rainy": (
        "0001110000",
        "0011111000",
        "0111111100",
        "1111111110",
        "0111111111",
        "0011111110",
        "0000000000",
        "0100100100",
        "0010010010",
        "0100100100",
    ),
    "mdi:weather-snowy": (
        "0001110000",
        "0011111000",
        "0111111100",
        "1111111110",
        "0111111111",
        "0011111110",
        "0000000000",
        "0101010100",
        "0010101000",
        "0101010100",
    ),
    "mdi:weather-lightning": (
        "0001110000",
        "0011111000",
        "0111111100",
        "1111111110",
        "0111111111",
        "0011111110",
        "0000110000",
        "0001100000",
        "0000110000",
        "0001100000",
    ),
}
