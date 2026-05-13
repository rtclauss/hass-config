from __future__ import annotations

import binascii
import os
from pathlib import Path
import struct
from typing import Any
import zlib

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:
    Image = None
    ImageDraw = None
    ImageFont = None

from .payload import DisplayPayload


WIDTH = 400
HEIGHT = 300
FOOTER_HEIGHT = 36
FOOTER_TEXT_SCALE = 2
FOOTER_TEXT_TOP = HEIGHT - 28

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
    rows = _payload_rows(payload)

    canvas.rectangle(0, 0, WIDTH, 14, accent)
    if _has_quote_layout(rows):
        _render_quote_layout(canvas, payload, rows, accent)
    else:
        _render_default_layout(canvas, payload, rows, accent)

    if payload.footer:
        canvas.rectangle(0, HEIGHT - FOOTER_HEIGHT, WIDTH, HEIGHT, BLACK)
        canvas.text(18, FOOTER_TEXT_TOP, payload.footer, scale=FOOTER_TEXT_SCALE, color=WHITE)

    return canvas.to_png()


def _payload_rows(payload: DisplayPayload) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for section in payload.sections:
        if section.get("type") != "rows":
            continue
        rows.extend(section.get("rows", ()))
    return rows


def _has_quote_layout(rows: list[dict[str, str]]) -> bool:
    return any(row.get("label") == "Quote" for row in rows)


def _render_default_layout(
    canvas: Canvas,
    payload: DisplayPayload,
    rows: list[dict[str, str]],
    accent: tuple[int, int, int],
) -> None:
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
    for row in rows:
        _render_row(canvas, row, payload.accent, y)
        y += 42


def _render_quote_layout(
    canvas: Canvas,
    payload: DisplayPayload,
    rows: list[dict[str, str]],
    accent: tuple[int, int, int],
) -> None:
    title = payload.title or payload.mode.replace("_", " ")
    subtitle = payload.subtitle
    quote = next((row.get("value", "") for row in rows if row.get("label") == "Quote"), "")
    speaker = next((row.get("value", "") for row in rows if row.get("label") == "Speaker"), "")
    weather = next((row for row in rows if row.get("label") == "Weather"), None)
    status = next((row for row in rows if row.get("label") == "Status"), None)

    canvas.text(18, 28, title, scale=3, color=BLACK)
    if subtitle:
        canvas.text(20, 60, subtitle, scale=1, color=BLACK)

    quote_lines = _wrap_text(quote, scale=3, max_width=352, max_lines=2)
    quote_top = 100 if len(quote_lines) == 1 else 86
    for index, line in enumerate(quote_lines):
        canvas.text_centered(200, quote_top + index * 34, line, scale=3, color=BLACK)
    attribution_top = quote_top + len(quote_lines) * 34 + 4
    if speaker:
        canvas.text_centered(200, attribution_top, f"- {speaker}", scale=1, color=BLACK)
        attribution_top += 16

    y = 196
    for row in (weather, status):
        if row is None:
            continue
        _render_row(canvas, row, payload.accent, y)
        y += 38


def _render_row(canvas: Canvas, row: dict[str, str], accent: str, y: int) -> None:
    level = row.get("level", "normal")
    row_color = LEVEL_COLORS.get(level, BLACK)
    if level in {"emphasis", "urgent"}:
        background_color = ACCENT_COLORS[accent]
        canvas.rectangle(18, y - 8, 382, y + 28, background_color)
        row_color = _text_color_for_background(background_color)
    label = row.get("label", "")
    canvas.icon(26, y - 4, row.get("icon", ""), scale=2, color=row_color)
    canvas.text(56, y, label, scale=2, color=row_color)
    canvas.text(170, y, row.get("value", ""), scale=2, color=row_color)


def _wrap_text(text: str, scale: int, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    max_chars = max(1, max_width // (6 * scale))
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if current == "" else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    return lines[:max_lines]


class Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        if Image is None or ImageDraw is None:
            self.image = None
            self.draw = None
            self.pixels = bytearray(WHITE * width * height)
        else:
            self.image = Image.new("RGB", (width, height), WHITE)
            self.draw = ImageDraw.Draw(self.image)
            self.pixels = None

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
        if right <= left or bottom <= top:
            return
        if self.draw is not None:
            self.draw.rectangle((left, top, right - 1, bottom - 1), fill=color)
            return
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
        font = _font_for_scale(scale)
        if font is not None:
            assert self.draw is not None
            text = _clip_text_to_width(self.draw, text, font, self.width - 8 - left)
            self.draw.text((left, top), text, font=font, fill=color)
            return

        x = left
        max_x = self.width - 8
        for char in text.upper():
            glyph = FONT.get(char, FONT["?"])
            if x + 5 * scale > max_x:
                break
            self._glyph(x, top, glyph, scale, color)
            x += 6 * scale

    def text_centered(
        self,
        center_x: int,
        top: int,
        text: str,
        scale: int,
        color: tuple[int, int, int],
    ) -> None:
        font = _font_for_scale(scale)
        if font is not None:
            assert self.draw is not None
            text = _clip_text_to_width(self.draw, text, font, self.width - 16)
            text_width = _text_width(self.draw, text, font)
            self.draw.text((max(0, center_x - text_width // 2), top), text, font=font, fill=color)
            return

        text_width = len(text) * 6 * scale
        self.text(max(0, center_x - text_width // 2), top, text, scale=scale, color=color)

    def icon(self, left: int, top: int, name: str, scale: int, color: tuple[int, int, int]) -> None:
        glyph = ICONS.get(name)
        if glyph is None:
            return
        self._glyph(left, top, glyph, scale, color)

    def to_png(self) -> bytes:
        if self.image is None:
            return self._legacy_to_png()
        image = _threshold_palette(self.image)
        return _image_to_png(image)

    def _legacy_to_png(self) -> bytes:
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
        if self.image is not None:
            self.image.putpixel((x, y), color)
            return
        assert self.pixels is not None
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


def _text_color_for_background(background: tuple[int, int, int]) -> tuple[int, int, int]:
    if background in {BLACK, RED}:
        return WHITE
    return BLACK


FONT_SIZE_BY_SCALE = {
    1: 11,
    2: 17,
    3: 34,
    4: 38,
}

FONT_CACHE: dict[tuple[str, int], Any | None] = {}

BOLD_FONT_CANDIDATES = (
    "INKY_FONT_BOLD",
    "/usr/share/fonts/truetype/msttcorefonts/trebucbd.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Trebuchet_MS_Bold.ttf",
    "/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf",
    "/Library/Fonts/Microsoft/Trebuchet MS Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/verdanab.ttf",
    "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    "/Library/Fonts/Microsoft/Verdana Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

REGULAR_FONT_CANDIDATES = (
    "INKY_FONT_REGULAR",
    "/usr/share/fonts/truetype/msttcorefonts/trebuc.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Trebuchet_MS.ttf",
    "/System/Library/Fonts/Supplemental/Trebuchet MS.ttf",
    "/Library/Fonts/Microsoft/Trebuchet MS.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/verdana.ttf",
    "/System/Library/Fonts/Supplemental/Verdana.ttf",
    "/Library/Fonts/Microsoft/Verdana.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font_for_scale(scale: int) -> Any | None:
    if ImageFont is None:
        return None
    style = "regular" if scale == 1 else "bold"
    size = FONT_SIZE_BY_SCALE.get(scale, 17)
    cache_key = (style, size)
    if cache_key in FONT_CACHE:
        return FONT_CACHE[cache_key]

    candidates = REGULAR_FONT_CANDIDATES if style == "regular" else BOLD_FONT_CANDIDATES
    for candidate in candidates:
        font_path = os.environ.get(candidate) if candidate.startswith("INKY_FONT_") else candidate
        if not font_path or not Path(font_path).exists():
            continue
        try:
            FONT_CACHE[cache_key] = ImageFont.truetype(font_path, size=size)
            return FONT_CACHE[cache_key]
        except OSError:
            continue

    FONT_CACHE[cache_key] = None
    return None


def _clip_text_to_width(draw: Any, text: str, font: Any, max_width: int) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    suffix = "..."
    clipped = text
    while clipped and _text_width(draw, clipped + suffix, font) > max_width:
        clipped = clipped[:-1].rstrip()
    return clipped + suffix if clipped else ""


def _text_width(draw: Any, text: str, font: Any) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _threshold_palette(image: Any) -> Any:
    assert Image is not None
    output = Image.new("RGB", image.size, WHITE)
    source = image.load()
    target = output.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = source[x, y]
            if r > 150 and g < 110 and b < 110:
                target[x, y] = RED
            elif (r + g + b) // 3 < 190:
                target[x, y] = BLACK
            else:
                target[x, y] = WHITE
    return output


def _image_to_png(image: Any) -> bytes:
    raw = bytearray()
    pixels = image.tobytes()
    row_width = image.width * 3
    for y in range(image.height):
        row_start = y * row_width
        raw.append(0)
        raw.extend(pixels[row_start : row_start + row_width])

    return (
        PNG_SIGNATURE
        + _chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0),
        )
        + _chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
        + _chunk(b"IEND", b"")
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
