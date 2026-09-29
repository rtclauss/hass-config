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

from .labels import EXCLUDING_FLAGS, FLAGS, LabelStore, jpeg_size

EVAL_SPLITS = ("verify", "test")


def _usable_readings(store: LabelStore) -> list[dict]:
    """Human-labeled full readings, excluding unreadable / non-totalizer frames."""
    events = store._events()
    splits = store._load_splits()
    usable = []
    for capture_id in store.list_capture_ids():
        labels = store.effective_labels(capture_id, events)
        if not labels["reading"] or set(labels["flags"]) & set(FLAGS):  # any flag: not a clean sample
            continue
        split = splits["capture"].get(capture_id)
        if split is None:
            continue
        usable.append({"id": capture_id, "digits": labels["reading"], "split": split, "labels": labels})
    return usable


def _spread(rows: list[dict], k: int) -> list[dict]:
    """Up to k rows evenly spaced through a time-ordered list (first and last kept)."""
    if len(rows) <= k:
        return rows
    if k == 1:
        return [rows[len(rows) // 2]]
    return [rows[round(i * (len(rows) - 1) / (k - 1))] for i in range(k)]


def export_golden(
    store: LabelStore,
    golden_dir: Path,
    *,
    splits: tuple[str, ...] = EVAL_SPLITS,
    max_per_value: int = 3,
) -> dict:
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
    # A long constant run yields dozens of near-identical frames of one reading;
    # keeping them all would let that one value dominate the eval set. Keep a few,
    # evenly spread in time, per (split, reading).
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in sorted(_usable_readings(store), key=lambda r: r["id"]):
        if row["split"] in splits:
            grouped.setdefault((row["split"], row["digits"]), []).append(row)
    chosen = [r for rows in grouped.values() for r in _spread(rows, max_per_value)]
    for row in sorted(chosen, key=lambda r: r["id"]):
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


def inferred_training_labels(store: LabelStore) -> list[dict]:
    """Weaker-tier train labels: readings implied for unlabeled captures that sit
    between two human labels of the same value (the meter only counts up). Train
    split only - never verify/test."""
    splits = store._load_splits()
    rows = []
    for capture_id, reading in sorted(store.inferred_readings().items()):
        if splits["value"].get(reading) != "train":
            continue
        rows.append(
            {"id": capture_id, "reading": reading, "digits": list(reading), "tier": "inferred"}
        )
    return rows


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
        if not labels["digits"] or set(labels["flags"]) & set(EXCLUDING_FLAGS):
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
