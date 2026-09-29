from __future__ import annotations

import json
from pathlib import Path

from water_meter import datasets, eval as water_meter_eval
from water_meter.labels import LabelStore

NOW = __import__("datetime").datetime(2026, 9, 29, tzinfo=__import__("datetime").timezone.utc)


def _jpeg(width: int, height: int) -> bytes:
    # SOI + SOF0 segment carrying the dimensions (enough for jpeg_size).
    sof = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + sof + b"\xff\xd9"


def _capture(tmp_path: Path, capture_id: str, *, w: int = 1280, h: int = 960) -> None:
    history = tmp_path / "images" / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / f"{capture_id}_crop.jpg").write_bytes(b"crop-" + capture_id.encode())
    (history / f"{capture_id}_raw.jpg").write_bytes(_jpeg(w, h))


def _store(tmp_path: Path) -> LabelStore:
    return LabelStore(tmp_path / "images", tmp_path / "state")


def test_jpeg_size_reads_the_sof_marker_and_tolerates_junk() -> None:
    assert datasets.jpeg_size(_jpeg(1280, 960)) == (1280, 960)
    assert datasets.jpeg_size(b"not a jpeg") == (0, 0)
    assert datasets.jpeg_size(b"") == (0, 0)


def test_export_golden_writes_eval_splits_only_and_is_loadable_by_the_harness(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for cid in ("20260901T000000Z", "20260901T010000Z", "20260901T020000Z", "20260901T030000Z"):
        _capture(tmp_path, cid)
    store.add_label("20260901T000000Z", "reading", value="02147013", split="test", now=NOW)
    store.add_label("20260901T010000Z", "reading", value="02147134", split="verify", now=NOW)
    store.add_label("20260901T020000Z", "reading", value="02147176", split="train", now=NOW)
    store.add_label("20260901T030000Z", "flag", flag="not_totalizer", value=True, now=NOW)

    golden = tmp_path / "golden"
    counts = datasets.export_golden(store, golden)

    assert counts == {"added": 2, "updated": 0, "total": 2}
    examples = {e.file: e for e in water_meter_eval.load_golden_set(golden)}  # verifies sha256
    assert set(examples) == {"20260901T000000Z.jpg", "20260901T010000Z.jpg"}
    assert examples["20260901T000000Z.jpg"].split == "test"
    assert examples["20260901T000000Z.jpg"].capture_width == 1280
    assert (golden / "raw" / "20260901T000000Z.jpg").exists()  # raw frames kept too

    # re-export is idempotent and never duplicates
    again = datasets.export_golden(store, golden)
    assert again == {"added": 0, "updated": 2, "total": 2}


def test_export_golden_keeps_existing_manifest_entries(tmp_path: Path) -> None:
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.json").write_text(
        json.dumps([{"file": "old.jpg", "digits": "02140000", "split": "verify"}])
    )
    store = _store(tmp_path)
    _capture(tmp_path, "20260901T000000Z")
    store.add_label("20260901T000000Z", "reading", value="02147013", split="test", now=NOW)

    datasets.export_golden(store, golden)

    files = [e["file"] for e in json.loads((golden / "manifest.json").read_text())]
    assert files == ["20260901T000000Z.jpg", "old.jpg"]


def test_training_labels_never_include_verify_or_test_and_allow_partial_digits(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for cid in ("20260901T000000Z", "20260901T010000Z", "20260901T020000Z"):
        _capture(tmp_path, cid)
    store.add_label("20260901T000000Z", "reading", value="02147013", split="train", now=NOW)
    store.add_label("20260901T010000Z", "reading", value="02147134", split="test", now=NOW)
    store.add_label("20260901T020000Z", "digit", position=4, value="7", split="train", now=NOW)

    rows = {r["id"]: r for r in datasets.human_training_labels(store)}

    assert set(rows) == {"20260901T000000Z", "20260901T020000Z"}
    assert rows["20260901T000000Z"]["digits"] == list("02147013")
    assert rows["20260901T020000Z"]["digits"][4] == "7"
    assert rows["20260901T020000Z"]["digits"][0] is None  # partial label, masked downstream
    assert rows["20260901T020000Z"]["reading"] is None


def test_export_golden_caps_near_duplicate_frames_per_value_keeping_them_spread(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [f"20260901T{h:02d}0000Z" for h in range(10)]
    for cid in ids:
        _capture(tmp_path, cid)
        store.add_label(cid, "reading", value="02148506", split="verify", now=NOW)

    golden = tmp_path / "golden"
    counts = datasets.export_golden(store, golden, max_per_value=3)

    files = sorted(e["file"] for e in json.loads((golden / "manifest.json").read_text()))
    assert counts["total"] == 3
    assert files == [f"{ids[0]}.jpg", f"{ids[4]}.jpg", f"{ids[9]}.jpg"]  # first, middle, last


def test_inferred_training_labels_are_train_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for split, prefix in (("train", "20260901"), ("verify", "20260902")):
        ids = [f"{prefix}T{h:02d}0000Z" for h in range(3)]
        for cid in ids:
            _capture(tmp_path, cid)
        value = "02148506" if split == "train" else "02147013"
        store.add_label(ids[0], "reading", value=value, split=split, now=NOW)
        store.add_label(ids[2], "reading", value=value, split=split, now=NOW)

    rows = datasets.inferred_training_labels(store)

    assert [r["id"] for r in rows] == ["20260901T010000Z"]
    assert rows[0]["digits"] == list("02148506") and rows[0]["tier"] == "inferred"
