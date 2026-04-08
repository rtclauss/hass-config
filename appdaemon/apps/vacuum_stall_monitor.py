from __future__ import annotations

import json
import math
import shutil
import struct
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import hassapi as hass
except ImportError:  # pragma: no cover - lets pytest import the module locally.
    class _HassBase:
        pass

    class hass:  # type: ignore[no-redef]
        Hass = _HassBase


MEDIA_ROOT = Path("/homeassistant/media")
DEFAULT_STORAGE_ROOT = MEDIA_ROOT / "vacuum_stalls"
SEGMENT_COLORS = (
    (25, 161, 161, 255),
    (122, 192, 55, 255),
    (223, 86, 24, 255),
    (247, 200, 65, 255),
    (118, 82, 182, 255),
    (0, 118, 255, 255),
)
BACKGROUND_COLOR = (245, 247, 250, 255)
FLOOR_COLOR = (222, 235, 255, 255)
WALL_COLOR = (29, 39, 56, 255)
PATH_COLOR = (255, 255, 255, 255)
ROBOT_COLOR = (220, 38, 38, 255)
CHARGER_COLOR = (22, 163, 74, 255)


@dataclass
class VacuumSample:
    captured_at: str
    area: float | None
    robot_position: tuple[int, int] | None
    segment_id: str | None
    room_name: str | None
    vacuum_state: str
    raw_png_path: Path
    rendered_png_path: Path | None
    metadata_path: Path

    def to_metadata(self, update: "StallUpdate") -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "area": self.area,
            "robot_position": list(self.robot_position) if self.robot_position else None,
            "segment_id": self.segment_id,
            "room_name": self.room_name,
            "vacuum_state": self.vacuum_state,
            "raw_png_path": str(self.raw_png_path),
            "rendered_png_path": str(self.rendered_png_path) if self.rendered_png_path else None,
            "samples_without_progress": update.samples_without_progress,
            "progress_detected": update.progress_detected,
            "stalled": update.stalled,
            "stalled_started": update.stalled_started,
            "stall_cleared": update.stall_cleared,
            "last_progress_at": update.last_progress_at,
            "stalled_at": update.stalled_at,
        }


@dataclass
class StallUpdate:
    progress_detected: bool
    stalled_started: bool
    stall_cleared: bool
    stalled: bool
    samples_without_progress: int
    last_progress_at: str | None
    stalled_at: str | None


@dataclass
class StallTracker:
    history_size: int
    stall_samples: int
    samples: list[VacuumSample] = field(default_factory=list)
    samples_without_progress: int = 0
    last_progress_at: str | None = None
    stalled_at: str | None = None
    stalled: bool = False
    notified: bool = False

    def ingest(self, sample: VacuumSample) -> StallUpdate:
        previous = self.samples[-1] if self.samples else None
        progress_detected = False
        stalled_started = False
        stall_cleared = False

        if previous is None:
            self.last_progress_at = sample.captured_at
        else:
            progress_detected = sample_made_progress(previous, sample)
            if progress_detected:
                self.samples_without_progress = 0
                self.last_progress_at = sample.captured_at
                if self.stalled:
                    stall_cleared = True
                self.stalled = False
                self.stalled_at = None
                self.notified = False
            else:
                self.samples_without_progress += 1
                if self.samples_without_progress >= self.stall_samples and not self.stalled:
                    self.stalled = True
                    self.stalled_at = sample.captured_at
                    stalled_started = True

        self.samples.append(sample)
        if len(self.samples) > self.history_size:
            self.samples = self.samples[-self.history_size :]

        return StallUpdate(
            progress_detected=progress_detected,
            stalled_started=stalled_started,
            stall_cleared=stall_cleared,
            stalled=self.stalled,
            samples_without_progress=self.samples_without_progress,
            last_progress_at=self.last_progress_at,
            stalled_at=self.stalled_at,
        )


def normalize_service(service_name: str) -> str:
    return service_name.replace(".", "/")


def slug_from_vacuum_entity(entity_id: str) -> str:
    return entity_id.split(".", 1)[-1].removeprefix("valetudo_")


def is_active_vacuum_state(state: str | None, active_states: tuple[str, ...] = ("cleaning", "returning")) -> bool:
    return bool(state and state in active_states)


def parse_numeric_state(raw_state: Any) -> float | None:
    if raw_state in (None, "", "unknown", "unavailable"):
        return None
    try:
        return float(raw_state)
    except (TypeError, ValueError):
        return None


def sample_made_progress(previous: VacuumSample, current: VacuumSample) -> bool:
    if previous.area is not None and current.area is not None and current.area > previous.area:
        return True
    if previous.robot_position != current.robot_position:
        return True
    if previous.segment_id != current.segment_id:
        return True
    return False


def build_segment_name_map(segment_state: Any) -> dict[str, str]:
    attributes = {}
    if isinstance(segment_state, dict):
        attributes = segment_state.get("attributes", segment_state)

    mapping: dict[str, str] = {}
    for key, value in attributes.items():
        if key in {"friendly_name", "icon"} or not isinstance(value, str):
            continue
        mapping[str(key)] = value
    return mapping


def resolve_room_name(segment_id: str | None, segment_map: dict[str, str]) -> str | None:
    if segment_id is None:
        return None
    return segment_map.get(str(segment_id))


def extract_ztxt_png_chunks(data: bytes) -> list[tuple[str, bytes]]:
    png_header = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(png_header):
        raise ValueError("Invalid PNG file header")

    chunks: list[tuple[str, bytes]] = []
    index = len(png_header)
    ended = False

    while index < len(data):
        if index + 8 > len(data):
            raise ValueError("PNG file ended prematurely")
        length = struct.unpack(">I", data[index : index + 4])[0]
        index += 4
        chunk_type = data[index : index + 4]
        index += 4
        chunk_data = data[index : index + length]
        index += length
        index += 4  # Skip CRC

        name = chunk_type.decode("ascii")
        if name == "IEND":
            ended = True
            break

        if name == "zTXt":
            try:
                separator = chunk_data.index(0)
            except ValueError as exc:
                raise ValueError("PNG zTXt chunk is missing a keyword terminator") from exc
            keyword = chunk_data[:separator].decode("latin1")
            if separator + 1 >= len(chunk_data):
                raise ValueError("PNG zTXt chunk is missing a compression flag")
            chunks.append((keyword, chunk_data[separator + 2 :]))

    if not ended:
        raise ValueError("PNG file ended prematurely: missing IEND chunk")

    return chunks


def preprocess_map_data(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metaData") or {}
    if metadata.get("version") == 2 and isinstance(data.get("layers"), list):
        for layer in data["layers"]:
            pixels = layer.setdefault("pixels", [])
            compressed = layer.get("compressedPixels") or []
            if pixels or not compressed:
                continue
            expanded: list[int] = []
            for index in range(0, len(compressed), 3):
                x_start = compressed[index]
                y = compressed[index + 1]
                count = compressed[index + 2]
                for offset in range(count):
                    expanded.extend((x_start + offset, y))
            layer["pixels"] = expanded
            layer.pop("compressedPixels", None)
    return data


def extract_valetudo_map_from_png(data: bytes) -> dict[str, Any]:
    for keyword, chunk_data in extract_ztxt_png_chunks(data):
        if keyword != "ValetudoMap":
            continue
        payload = zlib.decompress(chunk_data).decode("utf-8")
        parsed = json.loads(payload)
        return preprocess_map_data(parsed)
    raise ValueError("No ValetudoMap zTXt chunk found in PNG image")


def get_entities_by_type(map_data: dict[str, Any], entity_type: str) -> list[dict[str, Any]]:
    return [
        entity
        for entity in map_data.get("entities", [])
        if isinstance(entity, dict) and entity.get("type") == entity_type
    ]


def get_layers_by_type(map_data: dict[str, Any], layer_type: str) -> list[dict[str, Any]]:
    return [
        layer
        for layer in map_data.get("layers", [])
        if isinstance(layer, dict) and layer.get("type") == layer_type
    ]


def extract_robot_position(map_data: dict[str, Any]) -> tuple[int, int] | None:
    robots = get_entities_by_type(map_data, "robot_position")
    if not robots:
        return None
    points = robots[0].get("points") or []
    if len(points) < 2:
        return None
    return int(points[0]), int(points[1])


def extract_active_segment_id(map_data: dict[str, Any]) -> str | None:
    active_segments = []
    for layer in get_layers_by_type(map_data, "segment"):
        metadata = layer.get("metaData") or {}
        if metadata.get("active") and metadata.get("segmentId") is not None:
            active_segments.append(str(metadata["segmentId"]))

    if active_segments:
        return active_segments[0]

    segment_layers = get_layers_by_type(map_data, "segment")
    if len(segment_layers) == 1:
        metadata = segment_layers[0].get("metaData") or {}
        if metadata.get("segmentId") is not None:
            return str(metadata["segmentId"])

    return None


def calculate_bounding_box(map_data: dict[str, Any]) -> tuple[int, int, int, int]:
    pixel_size = int(map_data.get("pixelSize") or 1)
    size = map_data.get("size") or {}
    min_x = int((size.get("x") or 0) / pixel_size)
    min_y = int((size.get("y") or 0) / pixel_size)
    max_x = 0
    max_y = 0

    for layer in map_data.get("layers", []):
        dimensions = layer.get("dimensions") or {}
        x_bounds = dimensions.get("x") or {}
        y_bounds = dimensions.get("y") or {}
        min_x = min(min_x, int(x_bounds.get("min", min_x)))
        min_y = min(min_y, int(y_bounds.get("min", min_y)))
        max_x = max(max_x, int(x_bounds.get("max", max_x)))
        max_y = max(max_y, int(y_bounds.get("max", max_y)))

    return min_x, min_y, max_x, max_y


def _segment_color(segment_id: str | None) -> tuple[int, int, int, int]:
    if segment_id is None:
        return FLOOR_COLOR
    try:
        index = int(segment_id)
    except ValueError:
        index = sum(ord(char) for char in segment_id)
    return SEGMENT_COLORS[index % len(SEGMENT_COLORS)]


def _coord_to_map_pixel(value: int, pixel_size: int) -> int:
    return int(math.floor(value / pixel_size))


def _set_pixel_block(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    scale: int,
    color: tuple[int, int, int, int],
) -> None:
    if x >= width or y >= height:
        return
    max_x = min(width, x + scale)
    max_y = min(height, y + scale)
    for draw_y in range(y, max_y):
        row_offset = draw_y * width * 4
        for draw_x in range(x, max_x):
            offset = row_offset + (draw_x * 4)
            buffer[offset : offset + 4] = bytes(color)


def _draw_line(
    buffer: bytearray,
    width: int,
    height: int,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int, int],
) -> None:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy

    while True:
        _set_pixel_block(buffer, width, height, x0, y0, 1, color)
        if x0 == x1 and y0 == y1:
            break
        twice_error = 2 * error
        if twice_error >= dy:
            error += dy
            x0 += sx
        if twice_error <= dx:
            error += dx
            y0 += sy


def _draw_marker(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    size: int,
    color: tuple[int, int, int, int],
) -> None:
    half = max(1, size // 2)
    for marker_y in range(y - half, y + half + 1):
        for marker_x in range(x - half, x + half + 1):
            if 0 <= marker_x < width and 0 <= marker_y < height:
                _set_pixel_block(buffer, width, height, marker_x, marker_y, 1, color)


def _pack_png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def write_png_rgba(path: Path, width: int, height: int, rgba: bytes) -> None:
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA buffer size does not match the requested PNG dimensions")

    raw_scanlines = bytearray()
    stride = width * 4
    for row in range(height):
        raw_scanlines.append(0)  # Filter type 0
        start = row * stride
        raw_scanlines.extend(rgba[start : start + stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _pack_png_chunk(b"IHDR", ihdr),
            _pack_png_chunk(b"IDAT", zlib.compress(bytes(raw_scanlines))),
            _pack_png_chunk(b"IEND", b""),
        )
    )
    path.write_bytes(png)


def render_valetudo_map_png(map_data: dict[str, Any], output_path: Path, scale: int = 4) -> Path:
    pixel_size = int(map_data.get("pixelSize") or 1)
    min_x, min_y, max_x, max_y = calculate_bounding_box(map_data)
    width = max(1, (max_x - min_x + 2) * scale)
    height = max(1, (max_y - min_y + 2) * scale)
    image = bytearray(bytes(BACKGROUND_COLOR) * width * height)

    def draw_pixels(layer: dict[str, Any], color: tuple[int, int, int, int]) -> None:
        pixels = layer.get("pixels") or []
        for index in range(0, len(pixels), 2):
            x = (int(pixels[index]) - min_x) * scale
            y = (int(pixels[index + 1]) - min_y) * scale
            _set_pixel_block(image, width, height, x, y, scale, color)

    for floor_layer in get_layers_by_type(map_data, "floor"):
        draw_pixels(floor_layer, FLOOR_COLOR)

    for segment_layer in get_layers_by_type(map_data, "segment"):
        metadata = segment_layer.get("metaData") or {}
        draw_pixels(segment_layer, _segment_color(metadata.get("segmentId")))

    for wall_layer in get_layers_by_type(map_data, "wall"):
        draw_pixels(wall_layer, WALL_COLOR)

    for path_entity in get_entities_by_type(map_data, "path"):
        points = path_entity.get("points") or []
        if len(points) < 4:
            continue
        converted = [
            (
                (_coord_to_map_pixel(int(points[index]), pixel_size) - min_x) * scale,
                (_coord_to_map_pixel(int(points[index + 1]), pixel_size) - min_y) * scale,
            )
            for index in range(0, len(points), 2)
        ]
        for start, end in zip(converted, converted[1:]):
            _draw_line(image, width, height, start, end, PATH_COLOR)

    chargers = get_entities_by_type(map_data, "charger_location")
    if chargers:
        points = chargers[0].get("points") or []
        if len(points) >= 2:
            charger_x = (_coord_to_map_pixel(int(points[0]), pixel_size) - min_x) * scale
            charger_y = (_coord_to_map_pixel(int(points[1]), pixel_size) - min_y) * scale
            _draw_marker(image, width, height, charger_x, charger_y, scale + 1, CHARGER_COLOR)

    robots = get_entities_by_type(map_data, "robot_position")
    if robots:
        points = robots[0].get("points") or []
        if len(points) >= 2:
            robot_x = (_coord_to_map_pixel(int(points[0]), pixel_size) - min_x) * scale
            robot_y = (_coord_to_map_pixel(int(points[1]), pixel_size) - min_y) * scale
            _draw_marker(image, width, height, robot_x, robot_y, scale + 2, ROBOT_COLOR)

    write_png_rgba(output_path, width, height, bytes(image))
    return output_path


def prune_sample_artifacts(samples_dir: Path, keep: int) -> None:
    metadata_files = sorted(samples_dir.glob("*.json"))
    stale_files = metadata_files[:-keep] if keep > 0 else metadata_files

    for metadata_file in stale_files:
        stem = metadata_file.stem
        metadata_file.unlink(missing_ok=True)
        (samples_dir / f"{stem}_raw.png").unlink(missing_ok=True)
        (samples_dir / f"{stem}_rendered.png").unlink(missing_ok=True)


def media_url_for(path: Path) -> str | None:
    try:
        relative = path.relative_to(MEDIA_ROOT)
    except ValueError:
        return None
    return f"/media/local/{relative.as_posix()}"


class VacuumStallMonitor(hass.Hass):
    def initialize(self) -> None:
        self.vacuum_entity = self.args["vacuum_entity"]
        self.map_camera_entity = self.args["map_camera_entity"]
        self.rendered_camera_entity = self.args.get("rendered_camera_entity")
        self.area_sensor = self.args["area_sensor"]
        self.segments_sensor = self.args["segments_sensor"]
        self.friendly_name = self.args.get("friendly_name", self.vacuum_entity)
        self.notify_service = normalize_service(self.args.get("notify_service", "notify/all"))
        self.dashboard_url = self.args.get("dashboard_url", "/ryan-new-mushroom/cleaning-v2")
        self.sample_interval_sec = int(self.args.get("sample_interval_sec", 90))
        self.history_size = int(self.args.get("history_size", 12))
        self.stall_samples = int(self.args.get("stall_samples", 6))
        self.map_scale = int(self.args.get("map_scale", 4))
        self.active_states = tuple(self.args.get("active_states", ["cleaning", "returning"]))
        self.slug = slug_from_vacuum_entity(self.vacuum_entity)
        self.storage_root = Path(self.args.get("storage_root", str(DEFAULT_STORAGE_ROOT))) / self.slug
        self.samples_dir = self.storage_root / "samples"
        self.samples_dir.mkdir(parents=True, exist_ok=True)

        self.binary_entity = f"binary_sensor.valetudo_{self.slug}_stalled"
        self.status_entity = f"sensor.valetudo_{self.slug}_stall_status"
        self.poll_handle = None
        self.tracker = StallTracker(history_size=self.history_size, stall_samples=self.stall_samples)

        self.listen_state(self._handle_vacuum_state_change, self.vacuum_entity)
        current_state = self.get_state(self.vacuum_entity)

        if is_active_vacuum_state(current_state, self.active_states):
            self._start_monitoring()
        else:
            self._publish_runtime_entities(current_state or "idle")

    def _handle_vacuum_state_change(
        self,
        entity: str,
        attribute: str,
        old: str | None,
        new: str | None,
        kwargs: dict[str, Any],
    ) -> None:
        if is_active_vacuum_state(new, self.active_states):
            if self.poll_handle is None:
                self._start_monitoring()
        else:
            self._stop_monitoring(new or "idle")

    def _start_monitoring(self) -> None:
        if self.poll_handle is not None:
            return

        self.tracker = StallTracker(history_size=self.history_size, stall_samples=self.stall_samples)
        self.poll_handle = self.run_every(
            self._poll_once,
            datetime.now() + timedelta(seconds=1),
            self.sample_interval_sec,
        )
        self._publish_runtime_entities("monitoring")

    def _stop_monitoring(self, current_state: str) -> None:
        if self.poll_handle is not None:
            self.cancel_timer(self.poll_handle)
            self.poll_handle = None
        self.tracker = StallTracker(history_size=self.history_size, stall_samples=self.stall_samples)
        self._publish_runtime_entities(current_state)

    def _poll_once(self, kwargs: dict[str, Any]) -> None:
        current_state = self.get_state(self.vacuum_entity)
        if not is_active_vacuum_state(current_state, self.active_states):
            self._stop_monitoring(current_state or "idle")
            return

        try:
            sample = self._capture_sample(current_state)
        except Exception as exc:  # pragma: no cover - runtime integration path.
            self.log(f"{self.friendly_name}: failed to capture a stall sample: {exc}")
            return

        if sample is None:
            return

        update = self.tracker.ingest(sample)
        sample.metadata_path.write_text(
            json.dumps(sample.to_metadata(update), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        prune_sample_artifacts(self.samples_dir, self.history_size)

        if update.stalled:
            self._refresh_latest_artifacts(sample)
            if update.stalled_started and not self.tracker.notified:
                self._send_stall_notification(sample)
                self.tracker.notified = True

        self._publish_runtime_entities("stalled" if update.stalled else "monitoring", sample, update)

    def _capture_sample(self, vacuum_state: str) -> VacuumSample | None:
        captured_at = datetime.now(timezone.utc).replace(microsecond=0)
        stem = captured_at.strftime("%Y%m%dT%H%M%SZ")
        raw_png_path = self.samples_dir / f"{stem}_raw.png"
        rendered_png_path = self.samples_dir / f"{stem}_rendered.png"
        metadata_path = self.samples_dir / f"{stem}.json"

        self.call_service(
            "camera/snapshot",
            entity_id=self.map_camera_entity,
            filename=str(raw_png_path),
        )
        if not self._wait_for_file(raw_png_path):
            raise FileNotFoundError(f"Camera snapshot did not create {raw_png_path}")

        map_data = extract_valetudo_map_from_png(raw_png_path.read_bytes())
        segment_state = self.get_state(self.segments_sensor, attribute="all")
        segment_map = build_segment_name_map(segment_state)
        segment_id = extract_active_segment_id(map_data)
        room_name = resolve_room_name(segment_id, segment_map)
        area = parse_numeric_state(self.get_state(self.area_sensor))
        robot_position = extract_robot_position(map_data)

        rendered_path: Path | None = None
        if self.rendered_camera_entity:
            try:
                self.call_service(
                    "camera/snapshot",
                    entity_id=self.rendered_camera_entity,
                    filename=str(rendered_png_path),
                )
                if self._wait_for_file(rendered_png_path):
                    rendered_path = rendered_png_path
            except Exception as exc:  # pragma: no cover - runtime integration path.
                self.log(f"{self.friendly_name}: rendered camera snapshot failed: {exc}")

        if rendered_path is None:
            try:
                rendered_path = render_valetudo_map_png(map_data, rendered_png_path, scale=self.map_scale)
            except Exception as exc:  # pragma: no cover - runtime integration path.
                rendered_png_path.unlink(missing_ok=True)
                rendered_path = None
                self.log(f"{self.friendly_name}: raw map rendering failed: {exc}")

        return VacuumSample(
            captured_at=captured_at.isoformat(),
            area=area,
            robot_position=robot_position,
            segment_id=segment_id,
            room_name=room_name,
            vacuum_state=vacuum_state,
            raw_png_path=raw_png_path,
            rendered_png_path=rendered_path,
            metadata_path=metadata_path,
        )

    def _wait_for_file(self, path: Path, timeout_seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_size > 0:
                return True
            time.sleep(0.1)
        return path.exists() and path.stat().st_size > 0

    def _refresh_latest_artifacts(self, sample: VacuumSample) -> None:
        latest_json = self.storage_root / "latest.json"
        latest_raw = self.storage_root / "latest_raw.png"
        shutil.copy2(sample.metadata_path, latest_json)
        shutil.copy2(sample.raw_png_path, latest_raw)

        if sample.rendered_png_path and sample.rendered_png_path.exists():
            shutil.copy2(sample.rendered_png_path, self.storage_root / "latest.png")

    def _send_stall_notification(self, sample: VacuumSample) -> None:
        latest_png = self.storage_root / "latest.png"
        image_url = media_url_for(latest_png)
        room_phrase = sample.room_name or "an unknown room"
        data: dict[str, Any] = {"url": self.dashboard_url}
        if image_url and latest_png.exists():
            data["image"] = image_url

        self.call_service(
            self.notify_service,
            title=f"{self.friendly_name} stalled",
            message=f"Vacuum stopped in {room_phrase}",
            data=data,
        )

    def _publish_runtime_entities(
        self,
        status: str,
        sample: VacuumSample | None = None,
        update: StallUpdate | None = None,
    ) -> None:
        latest_png = self.storage_root / "latest.png"
        latest_json = self.storage_root / "latest.json"
        image_url = media_url_for(latest_png)

        metadata: dict[str, Any] = {}
        if sample is not None and update is not None:
            metadata = sample.to_metadata(update)
        elif latest_json.exists():
            try:
                metadata = json.loads(latest_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {}

        state_attributes = {
            "friendly_name": f"{self.friendly_name} stall status",
            "icon": "mdi:robot-vacuum-alert",
            "room": metadata.get("room_name"),
            "segment_id": metadata.get("segment_id"),
            "last_progress_at": metadata.get("last_progress_at"),
            "stalled_at": metadata.get("stalled_at"),
            "samples_without_progress": metadata.get("samples_without_progress", 0),
            "latest_json": media_url_for(latest_json),
            "latest_raw_image": media_url_for(self.storage_root / "latest_raw.png"),
        }
        if image_url and latest_png.exists():
            state_attributes["entity_picture"] = f"{image_url}?v={int(time.time())}"

        self.set_state(self.status_entity, state=status, attributes=state_attributes)
        self.set_state(
            self.binary_entity,
            state="on" if status == "stalled" else "off",
            attributes={
                "friendly_name": f"{self.friendly_name} stalled",
                "device_class": "problem",
                "icon": "mdi:robot-vacuum-alert",
            },
        )
