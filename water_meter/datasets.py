"""Exporters from the human label store to the datasets each consumer needs.

The label store (labels.py) is the single source of truth. This module turns
it into (a) the sealed eval manifest under water_meter/golden_set/ and (b)
training labels, enforcing the split policy at the boundary: training code
only ever sees `train`-split, human-labeled captures.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .labels import FLAGS, LabelStore

EVAL_SPLITS = ("verify", "test")


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's SOF marker, or (0, 0) if unparseable."""
    i = 2
    while i + 9 < len(data) and data[0:2] == b"\xff\xd8":
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
    return (0, 0)


def _usable_readings(store: LabelStore) -> list[dict]:
    """Human-labeled full readings, excluding unreadable / non-totalizer frames."""
    events = store._events()
    splits = store._load_splits()
    usable = []
    for capture_id in store.list_capture_ids():
        labels = store.effective_labels(capture_id, events)
        if not labels["reading"] or set(labels["flags"]) & set(FLAGS):
            continue
        split = splits["capture"].get(capture_id)
        if split is None:
            continue
        usable.append({"id": capture_id, "digits": labels["reading"], "split": split, "labels": labels})
    return usable


def export_golden(store: LabelStore, golden_dir: Path, *, splits: tuple[str, ...] = EVAL_SPLITS) -> dict:
    """Write verify/test captures into golden_dir and merge them into its
    manifest (existing entries kept; same-file entries refreshed). Crops are
    what eval.py scores; raw frames are kept too so recalibration or a
    resolution change never strands the labeled data."""
    golden_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = golden_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = {e["file"]: e for e in json.loads(manifest_path.read_text(encoding="utf-8"))}
    added = updated = 0
    for row in _usable_readings(store):
        if row["split"] not in splits:
            continue
        files = store.capture_files(row["id"])
        crop = files.get("crop")
        if crop is None:
            continue
        name = f"{row['id']}.jpg"
        shutil.copy2(crop, golden_dir / name)
        width = height = 0
        if "raw" in files:
            raw_dir = golden_dir / "raw"
            raw_dir.mkdir(exist_ok=True)
            shutil.copy2(files["raw"], raw_dir / name)
            width, height = jpeg_size(files["raw"].read_bytes())
        entry = {
            "file": name,
            "digits": row["digits"],
            "capture_width": width or manifest.get(name, {}).get("capture_width", 0),
            "capture_height": height or manifest.get(name, {}).get("capture_height", 0),
            "split": row["split"],
            "sha256": hashlib.sha256((golden_dir / name).read_bytes()).hexdigest(),
        }
        if name in manifest:
            updated += 1
        else:
            added += 1
        manifest[name] = entry
    manifest_path.write_text(
        json.dumps([manifest[k] for k in sorted(manifest)], indent=2) + "\n", encoding="utf-8"
    )
    return {"added": added, "updated": updated, "total": len(manifest)}


def human_training_labels(store: LabelStore) -> list[dict]:
    """Per-capture human labels usable for training: train split only, with
    per-position digit labels (partial allowed; missing positions are None)."""
    events = store._events()
    splits = store._load_splits()
    rows = []
    for capture_id in store.list_capture_ids():
        if splits["capture"].get(capture_id) != "train":
            continue
        labels = store.effective_labels(capture_id, events)
        if not labels["digits"] or set(labels["flags"]) & {"unreadable"}:
            continue
        rows.append(
            {
                "id": capture_id,
                "reading": labels["reading"],
                "digits": [labels["digits"].get(str(i)) for i in range(store.digit_count)],
                "not_totalizer": "not_totalizer" in labels["flags"],
            }
        )
    return rows
