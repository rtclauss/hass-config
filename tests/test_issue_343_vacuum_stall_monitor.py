from __future__ import annotations

import importlib.util
import json
import struct
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "appdaemon" / "apps" / "vacuum_stall_monitor.py"
APP_CONFIG_PATH = ROOT / "appdaemon" / "apps" / "vacuum_stall_monitor.yaml"
DASHBOARD_PATH = ROOT / ".storage" / "lovelace.ryan_new_mushroom"
GITIGNORE_PATH = ROOT / ".gitignore"


def _load_module():
    spec = importlib.util.spec_from_file_location("vacuum_stall_monitor", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample(module, tmp_path: Path, captured_at: datetime, area: float, position: tuple[int, int], segment_id: str):
    stem = captured_at.strftime("%Y%m%dT%H%M%SZ")
    return module.VacuumSample(
        captured_at=captured_at.isoformat(),
        area=area,
        robot_position=position,
        segment_id=segment_id,
        room_name="Kitchen",
        vacuum_state="cleaning",
        raw_png_path=tmp_path / f"{stem}_raw.png",
        rendered_png_path=tmp_path / f"{stem}_rendered.png",
        metadata_path=tmp_path / f"{stem}.json",
    )


def _pack_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _build_png_with_valetudo_chunk(map_data: dict) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff\xff")
    ztxt = b"ValetudoMap\x00\x00" + zlib.compress(json.dumps(map_data).encode("utf-8"))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _pack_chunk(b"IHDR", ihdr),
            _pack_chunk(b"zTXt", ztxt),
            _pack_chunk(b"IDAT", idat),
            _pack_chunk(b"IEND", b""),
        )
    )


def test_stall_tracker_alerts_once_and_resets_after_progress(tmp_path: Path) -> None:
    module = _load_module()
    tracker = module.StallTracker(history_size=12, stall_samples=6)
    now = datetime(2026, 4, 2, 16, 0, tzinfo=timezone.utc)

    first = tracker.ingest(_sample(module, tmp_path, now, 0.0, (0, 0), "1"))
    assert first.progress_detected is False
    assert first.stalled is False

    moved = tracker.ingest(_sample(module, tmp_path, now + timedelta(minutes=1), 10.0, (10, 5), "1"))
    assert moved.progress_detected is True
    assert moved.samples_without_progress == 0

    stall_events = 0
    for offset in range(2, 8):
        update = tracker.ingest(_sample(module, tmp_path, now + timedelta(minutes=offset), 10.0, (10, 5), "1"))
        stall_events += int(update.stalled_started)

    assert stall_events == 1
    assert tracker.stalled is True
    assert tracker.samples_without_progress == 6

    repeat = tracker.ingest(_sample(module, tmp_path, now + timedelta(minutes=8), 10.0, (10, 5), "1"))
    assert repeat.stalled_started is False

    recovered = tracker.ingest(_sample(module, tmp_path, now + timedelta(minutes=9), 12.0, (12, 7), "2"))
    assert recovered.progress_detected is True
    assert recovered.stall_cleared is True
    assert recovered.stalled is False
    assert tracker.samples_without_progress == 0


def test_monitor_only_counts_cleaning_and_returning_states() -> None:
    module = _load_module()

    assert module.is_active_vacuum_state("cleaning") is True
    assert module.is_active_vacuum_state("returning") is True
    assert module.is_active_vacuum_state("docked") is False
    assert module.is_active_vacuum_state("unavailable") is False


def test_extract_valetudo_map_and_render_png(tmp_path: Path) -> None:
    module = _load_module()
    map_data = {
        "__class": "ValetudoMap",
        "metaData": {"version": 2, "nonce": "abc123"},
        "size": {"x": 40, "y": 40},
        "pixelSize": 5,
        "layers": [
            {
                "type": "floor",
                "metaData": {"area": 4},
                "pixels": [],
                "compressedPixels": [0, 0, 2, 0, 1, 2],
                "dimensions": {
                    "x": {"min": 0, "max": 1, "mid": 0, "avg": 0},
                    "y": {"min": 0, "max": 1, "mid": 0, "avg": 0},
                    "pixelCount": 4,
                },
            },
            {
                "type": "segment",
                "metaData": {"area": 2, "segmentId": "7", "active": True},
                "pixels": [0, 0, 1, 0],
                "dimensions": {
                    "x": {"min": 0, "max": 1, "mid": 0, "avg": 0},
                    "y": {"min": 0, "max": 0, "mid": 0, "avg": 0},
                    "pixelCount": 2,
                },
            },
            {
                "type": "wall",
                "metaData": {"area": 1},
                "pixels": [1, 1],
                "dimensions": {
                    "x": {"min": 1, "max": 1, "mid": 1, "avg": 1},
                    "y": {"min": 1, "max": 1, "mid": 1, "avg": 1},
                    "pixelCount": 1,
                },
            },
        ],
        "entities": [
            {"type": "robot_position", "points": [20, 10], "metaData": {"angle": 90}},
            {"type": "charger_location", "points": [5, 5], "metaData": {}},
            {"type": "path", "points": [0, 0, 20, 10], "metaData": {}},
        ],
    }

    raw_png = _build_png_with_valetudo_chunk(map_data)
    parsed = module.extract_valetudo_map_from_png(raw_png)

    assert parsed["layers"][0]["pixels"] == [0, 0, 1, 0, 0, 1, 1, 1]
    assert module.extract_robot_position(parsed) == (20, 10)
    assert module.extract_active_segment_id(parsed) == "7"
    assert module.resolve_room_name("7", {"7": "Office"}) == "Office"

    output_path = tmp_path / "rendered.png"
    module.render_valetudo_map_png(parsed, output_path, scale=4)
    rendered = output_path.read_bytes()
    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(rendered) > 100


def test_prune_sample_artifacts_keeps_latest_n(tmp_path: Path) -> None:
    module = _load_module()
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    (tmp_path / "latest.png").write_bytes(b"latest")

    for index in range(15):
        stem = f"20260402T160{index:02d}Z"
        (samples_dir / f"{stem}.json").write_text("{}", encoding="utf-8")
        (samples_dir / f"{stem}_raw.png").write_bytes(b"raw")
        (samples_dir / f"{stem}_rendered.png").write_bytes(b"rendered")

    module.prune_sample_artifacts(samples_dir, keep=12)

    assert len(list(samples_dir.glob("*.json"))) == 12
    assert len(list(samples_dir.glob("*_raw.png"))) == 12
    assert len(list(samples_dir.glob("*_rendered.png"))) == 12
    assert (tmp_path / "latest.png").exists()


def test_config_and_dashboard_wire_all_vacuums() -> None:
    config_text = APP_CONFIG_PATH.read_text(encoding="utf-8")
    dashboard_text = DASHBOARD_PATH.read_text(encoding="utf-8")
    gitignore_text = GITIGNORE_PATH.read_text(encoding="utf-8")

    for entity_id in (
        "vacuum.valetudo_mainlevel",
        "vacuum.valetudo_den",
        "vacuum.valetudo_upstairs_vacuum",
    ):
        assert entity_id in config_text

    for sensor_id in (
        "sensor.valetudo_mainlevel_stall_status",
        "sensor.valetudo_den_stall_status",
        "sensor.valetudo_upstairs_vacuum_stall_status",
        "binary_sensor.valetudo_mainlevel_stalled",
        "binary_sensor.valetudo_den_stalled",
        "binary_sensor.valetudo_upstairs_vacuum_stalled",
    ):
        assert sensor_id in dashboard_text

    assert "Ground Floor Stall Evidence" in dashboard_text
    assert "Den Stall Evidence" in dashboard_text
    assert "Upstairs Stall Evidence" in dashboard_text
    assert "!appdaemon/apps/vacuum_stall_monitor.py" in gitignore_text
    assert "!appdaemon/apps/vacuum_stall_monitor.yaml" in gitignore_text
