"""Human label store for the labeling UI (label_ui.py) and dataset exporters.

Labels are an append-only event log (`labels.jsonl`, latest wins, full audit
trail) so a bad batch can be reverted by replaying without it. Two label
kinds exist: a full reading (all digits of a capture) and a single digit
(position + value, possibly partial), plus boolean flags (`unreadable`,
`not_totalizer` - the display cycles to a non-totalizer field on light
pulses).

Every labeled capture is snapshotted into `image_dir/labeled/<capture_id>/`
because `history/` rotates; nothing in this module ever deletes from there.

Splits (train / verify / test) come from a fixed *time-block schedule*, not a
random hash: the meter is monotonic, so time order is value order, and
contiguous blocks make eval measure reading values the model has not seen
(interpolation/extrapolation) instead of near-duplicate frames of a value it
trained on. A block is 8 hours; a 20-block cycle is 14 train / 3 verify / 3 test
with eval blocks never adjacent, and train captures within an hour of an eval
block are `embargo` (kept, but excluded from training) because neighbouring
frames share their value and lighting. Proportions are guaranteed over a cycle
rather than left to a hash's luck at small n.

Captures sharing one reading form a value group and share a split (the most
sealed of its members), and splits are sticky: once assigned they only ever move
toward the more sealed split (train -> embargo -> verify -> test), never back,
because moving an item out of test would leak it into training.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil

CAPTURE_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")
IMAGE_NAMES = ("raw", "crop") + tuple(f"digit{i}" for i in range(8))
SPLITS = ("train", "embargo", "verify", "test")
SPLIT_RANK = {name: rank for rank, name in enumerate(SPLITS)}
FLAGS = ("unreadable", "not_totalizer", "bad_frame")
# Flags that take a capture out of every dataset and the labeling queue.
EXCLUDING_FLAGS = ("unreadable", "bad_frame")
SCHEDULE_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
BLOCK_SECONDS = 8 * 3600
# T=train, V=verify, E=test. 14/3/3 = 70/15/15; eval blocks are never adjacent.
SCHEDULE = "TTTVTTETTVTTETTVTTET"
EMBARGO_SECONDS = 3600
# While a split is under its target, unlabeled captures scheduled into it are
# offered first (eval data is the scarce kind).
EVAL_TARGETS = {"test": 60, "verify": 30}
_SCHEDULE_NAMES = {"T": "train", "V": "verify", "E": "test"}
DYNAMIC_EXAMPLES_LIMIT = 12


class LabelError(ValueError):
    """Invalid label request (bad id, bad value, unknown capture)."""


def capture_time(capture_id: str) -> datetime:
    return datetime.strptime(capture_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def more_sealed(a: str | None, b: str | None) -> str | None:
    candidates = [s for s in (a, b) if s]
    return max(candidates, key=SPLIT_RANK.__getitem__) if candidates else None


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


def scheduled_split(capture_id: str) -> str:
    """The split a capture's timestamp falls into (see the module docstring)."""
    seconds = (capture_time(capture_id) - SCHEDULE_EPOCH).total_seconds()
    block = int(seconds // BLOCK_SECONDS)
    kind = SCHEDULE[block % len(SCHEDULE)]
    if kind == "T":
        offset = seconds - block * BLOCK_SECONDS
        before = SCHEDULE[(block - 1) % len(SCHEDULE)]
        after = SCHEDULE[(block + 1) % len(SCHEDULE)]
        if (before != "T" and offset < EMBARGO_SECONDS) or (
            after != "T" and BLOCK_SECONDS - offset < EMBARGO_SECONDS
        ):
            return "embargo"
    return _SCHEDULE_NAMES[kind]


def append_dynamic_example(
    examples_dir: Path, source_crop: Path, digits: str, stamp: str, limit: int = DYNAMIC_EXAMPLES_LIMIT
) -> bool:
    """Add one (crop, digits) pair to the rolling dynamic few-shot pool that
    ocr.load_dynamic_examples reads. Oldest entries (and their images) are
    dropped past `limit`. Returns False if the source crop is missing."""
    if not source_crop.exists():
        return False
    examples_dir.mkdir(parents=True, exist_ok=True)
    index_path = examples_dir / "index.json"
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError):
        entries = []
    file_name = f"{stamp}_{digits}.jpg"
    (examples_dir / file_name).write_bytes(source_crop.read_bytes())
    # One example per reading: near-identical frames of the same value add no
    # teaching signal, crowd out diverse examples in the small window the prompt
    # uses, and invite the model to copy an example's answer. The newest wins.
    for stale in [e for e in entries if e.get("digits") == digits and e.get("file") != file_name]:
        try:
            (examples_dir / str(stale["file"])).unlink(missing_ok=True)
        except (OSError, KeyError, TypeError):
            pass
    entries = [e for e in entries if e.get("digits") != digits and e.get("file") != file_name]
    entries.append({"file": file_name, "digits": digits})
    while len(entries) > limit:
        stale = entries.pop(0)
        try:
            (examples_dir / str(stale["file"])).unlink(missing_ok=True)
        except (OSError, KeyError, TypeError):
            pass
    index_path.write_text(json.dumps(entries), encoding="utf-8")
    return True


class LabelStore:
    def __init__(
        self,
        image_dir: Path,
        state_dir: Path,
        *,
        calibration_path: Path | None = None,
        digit_count: int = 8,
    ) -> None:
        self.history_dir = image_dir / "history"
        self.rejects_dir = image_dir / "rejects"
        self.labeled_dir = image_dir / "labeled"
        self.image_dir = image_dir
        self.events_path = state_dir / "labels.jsonl"
        self.splits_path = state_dir / "label_splits.json"
        self.calibration_path = calibration_path
        self.digit_count = digit_count

    # ---- files -------------------------------------------------------

    def _check_id(self, capture_id: str) -> None:
        if not isinstance(capture_id, str) or not CAPTURE_ID_RE.match(capture_id):
            raise LabelError(f"bad capture id {capture_id!r}")

    def capture_files(self, capture_id: str) -> dict[str, Path]:
        """Existing image/sidecar files for a capture: the labeled snapshot
        wins over history (history may have rotated a file away)."""
        self._check_id(capture_id)
        files: dict[str, Path] = {}
        for name in IMAGE_NAMES:
            for base in (self.labeled_dir / capture_id, self.history_dir):
                path = base / (f"{name}.jpg" if base.name == capture_id else f"{capture_id}_{name}.jpg")
                if path.exists():
                    files[name] = path
                    break
        for base in (self.labeled_dir / capture_id, self.history_dir):
            path = base / ("read.json" if base.name == capture_id else f"{capture_id}_read.json")
            if path.exists():
                files["read"] = path
                break
        return files

    def expected_frame_size(self) -> tuple[int, int] | None:
        """(width, height) the current calibration was drawn for, or None."""
        if self.calibration_path is None or not self.calibration_path.exists():
            return None
        try:
            data = json.loads(self.calibration_path.read_text(encoding="utf-8"))
            return int(data.get("capture_width", 640)), int(data.get("capture_height", 480))
        except (OSError, ValueError, TypeError):
            return None

    def frame_size(self, capture_id: str) -> tuple[int, int]:
        raw = self.capture_files(capture_id).get("raw")
        if raw is None:
            return (0, 0)
        try:
            with raw.open("rb") as handle:
                return jpeg_size(handle.read(65536))
        except OSError:
            return (0, 0)

    def is_legacy(self, capture_id: str, expected: tuple[int, int] | None = None) -> bool:
        """True when the current ROI/digit boxes/rotation can't apply to this
        capture: no raw frame, or captured at a different resolution (e.g. the
        640x480 era - a different field of view, not a scaled copy)."""
        expected = expected or self.expected_frame_size()
        if expected is None:
            return False
        return self.frame_size(capture_id) != expected

    def capture_exists(self, capture_id: str) -> bool:
        return "crop" in self.capture_files(capture_id) or "raw" in self.capture_files(capture_id)

    def read_sidecar(self, capture_id: str) -> dict | None:
        path = self.capture_files(capture_id).get("read")
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def was_rejected(self, capture_id: str) -> bool:
        sidecar = self.read_sidecar(capture_id)
        if sidecar is not None:
            return not sidecar.get("accepted", True)
        return bool(list(self.rejects_dir.glob(f"{capture_id}_*.jpg"))) if self.rejects_dir.exists() else False

    def snapshot(self, capture_id: str) -> Path:
        """Copy a capture's files into labeled/<id>/ (idempotent, never deletes)."""
        self._check_id(capture_id)
        dest = self.labeled_dir / capture_id
        dest.mkdir(parents=True, exist_ok=True)
        for name, path in self.capture_files(capture_id).items():
            target = dest / (f"{name}.json" if name == "read" else f"{name}.jpg")
            if not target.exists():
                shutil.copy2(path, target)
        if self.calibration_path is not None and self.calibration_path.exists():
            target = dest / "calibration.json"
            if not target.exists():
                shutil.copy2(self.calibration_path, target)
        meta = dest / "meta.json"
        if not meta.exists():
            meta.write_text(
                json.dumps({"snapshotted_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
        return dest

    def list_capture_ids(self) -> list[str]:
        ids: set[str] = set()
        if self.history_dir.exists():
            ids.update(p.name.split("_", 1)[0] for p in self.history_dir.glob("*_crop.jpg"))
        if self.labeled_dir.exists():
            ids.update(p.name for p in self.labeled_dir.iterdir() if p.is_dir())
        return sorted((i for i in ids if CAPTURE_ID_RE.match(i)), reverse=True)

    # ---- events / effective labels -----------------------------------

    def _events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        events = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        return events

    def _append(self, event: dict) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def effective_labels(self, capture_id: str, events: list[dict] | None = None) -> dict:
        """Replay events: a reading label sets every position, a later digit
        label overrides one position, latest wins; flags toggle."""
        reading: str | None = None
        digits: dict[int, str] = {}
        flags: set[str] = set()
        labeled_at = None
        for event in events if events is not None else self._events():
            if event.get("capture_id") != capture_id:
                continue
            kind = event.get("kind")
            if kind == "reading":
                reading = event["value"]
                digits = {i: c for i, c in enumerate(reading)}
                labeled_at = event.get("ts")
            elif kind == "digit":
                digits[int(event["position"])] = event["value"]
                reading = "".join(digits[i] for i in range(self.digit_count)) if all(
                    i in digits for i in range(self.digit_count)
                ) else None
                labeled_at = event.get("ts")
            elif kind == "flag":
                (flags.add if event.get("value") else flags.discard)(event["flag"])
                labeled_at = event.get("ts")
        return {
            "reading": reading,
            "digits": {str(k): v for k, v in sorted(digits.items())},
            "flags": sorted(flags),
            "labeled_at": labeled_at,
        }

    # ---- splits ------------------------------------------------------

    def _load_splits(self) -> dict:
        if self.splits_path.exists():
            try:
                data = json.loads(self.splits_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("capture", {})
                    data.setdefault("value", {})
                    data.setdefault("groups", {})
                    return data
            except (OSError, ValueError):
                pass
        return {"capture": {}, "value": {}, "groups": {}}

    def _save_splits(self, data: dict) -> None:
        self.splits_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.splits_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.splits_path)

    def split_of(self, capture_id: str) -> str | None:
        return self._load_splits()["capture"].get(capture_id)

    def value_split(self, reading: str) -> str | None:
        return self._load_splits()["value"].get(reading)

    def _ensure_split(
        self, capture_id: str, reading: str | None, now: datetime, forced: str | None = None
    ) -> str:
        data = self._load_splits()
        existing = more_sealed(
            data["capture"].get(capture_id), data["value"].get(reading) if reading else None
        )
        if forced:
            existing = more_sealed(existing, forced)
        if existing is None:
            existing = scheduled_split(capture_id)
        changed: list[str] = []
        previous = dict(data["capture"])
        data["capture"][capture_id] = more_sealed(data["capture"].get(capture_id), existing)
        if reading:
            members = data["groups"].setdefault(reading, [])
            if capture_id not in members:
                members.append(capture_id)
            data["value"][reading] = existing
            for member in members:  # promote siblings, never demote
                data["capture"][member] = more_sealed(data["capture"].get(member), existing)
        for member, split in data["capture"].items():
            if member in previous and previous[member] != split:
                changed.append(member)
        self._save_splits(data)
        for member in changed:
            self._append(
                {
                    "ts": now.isoformat(),
                    "kind": "split",
                    "capture_id": member,
                    "value": data["capture"][member],
                    "reason": "value group sealed",
                }
            )
        return existing

    # ---- labeling ----------------------------------------------------

    def add_label(
        self,
        capture_id: str,
        kind: str,
        *,
        value: str | bool | None = None,
        position: int | None = None,
        flag: str | None = None,
        labeler: str = "human",
        source: str = "human",
        split: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(timezone.utc)
        self._check_id(capture_id)
        if not self.capture_exists(capture_id):
            raise LabelError(f"unknown capture {capture_id}")

        event: dict = {
            "ts": now.isoformat(),
            "capture_id": capture_id,
            "kind": kind,
            "labeler": labeler,
            "source": source,
        }
        reading_for_split: str | None = None
        if kind == "reading":
            if not (isinstance(value, str) and value.isdigit() and len(value) == self.digit_count):
                raise LabelError(f"a reading must be exactly {self.digit_count} digits")
            event["value"] = value
            reading_for_split = value
        elif kind == "digit":
            if not (isinstance(position, int) and 0 <= position < self.digit_count):
                raise LabelError("bad digit position")
            if not (isinstance(value, str) and len(value) == 1 and value.isdigit()):
                raise LabelError("a digit label must be one digit 0-9")
            event["position"] = position
            event["value"] = value
        elif kind == "flag":
            if flag not in FLAGS:
                raise LabelError(f"unknown flag {flag!r}")
            event["flag"] = flag
            event["value"] = bool(value)
        else:
            raise LabelError(f"unknown label kind {kind!r}")
        if split is not None and split not in SPLITS:
            raise LabelError(f"unknown split {split!r}")

        self.snapshot(capture_id)
        assigned = self._ensure_split(capture_id, reading_for_split, now, forced=split)
        event["split"] = assigned
        self._append(event)

        if kind == "reading" and assigned == "train" and not (
            set(self.effective_labels(capture_id)["flags"]) & set(EXCLUDING_FLAGS)
        ):
            crop = self.capture_files(capture_id).get("crop")
            if crop is not None:
                append_dynamic_example(
                    self.image_dir / "human_corrections", crop, value, capture_id
                )
        return self.item(capture_id)

    # ---- views -------------------------------------------------------

    def item(
        self,
        capture_id: str,
        *,
        blind: bool = False,
        events: list[dict] | None = None,
        splits: dict | None = None,
    ) -> dict:
        files = self.capture_files(capture_id)
        labels = self.effective_labels(capture_id, events)
        sidecar = self.read_sidecar(capture_id) or {}
        split = (splits if splits is not None else self._load_splits())["capture"].get(capture_id)
        flags = set(labels["flags"])
        status = (
            "excluded"
            if "bad_frame" in flags
            else "labeled"
            if labels["reading"] or "unreadable" in flags
            else "partial"
            if labels["digits"] or flags
            else "unlabeled"
        )
        size = self.frame_size(capture_id)
        item = {
            "id": capture_id,
            "files": sorted(files),
            "frame": {"width": size[0], "height": size[1]},
            "legacy": self.is_legacy(capture_id),
            "labels": labels,
            "split": split,
            "scheduled_split": scheduled_split(capture_id),
            "status": status,
            "rejected": self.was_rejected(capture_id),
            "reason": sidecar.get("reason"),
        }
        item["guess"] = None if blind else sidecar.get("raw_digits")
        if blind:
            item["reason"] = None
        return item

    def queue(self, mode: str = "queue", limit: int = 50, *, blind: bool = False) -> dict:
        """mode: queue (unlabeled: pipeline-rejected first, then captures scheduled
        into an eval split that is still under its target, then distinct guessed
        values), all, labeled, excluded (bad frames) or legacy (frames the current
        calibration can't apply to, e.g. other resolutions - never in the queue)."""
        events = self._events()
        splits = self._load_splits()
        ids = self.list_capture_ids()
        items = []
        for capture_id in ids:
            item = self.item(capture_id, events=events, splits=splits)
            done = item["status"] in ("labeled", "excluded")
            if mode == "queue" and (done or item["legacy"]):
                continue
            if mode == "legacy" and (item["status"] == "excluded" or not item["legacy"]):
                continue
            if mode == "labeled" and item["status"] != "labeled":
                continue
            if mode == "excluded" and item["status"] != "excluded":
                continue
            items.append(item)
        if mode == "queue":
            labeled_by_split = self.stats()["by_split"]
            needy = {
                name for name, target in EVAL_TARGETS.items() if labeled_by_split.get(name, 0) < target
            }
            seen_values: set[str] = set()
            rejected, needed, diverse, rest = [], [], [], []
            for item in items:
                fresh_value = bool(item["guess"]) and item["guess"] not in seen_values
                if item["rejected"]:
                    rejected.append(item)
                elif item["scheduled_split"] in needy and (fresh_value or not item["guess"]):
                    needed.append(item)
                elif fresh_value:
                    diverse.append(item)
                else:
                    rest.append(item)
                if fresh_value:
                    seen_values.add(item["guess"])
            items = rejected + needed + diverse + rest
        depth = len(items)
        if blind:
            for item in items:
                item["guess"] = None
                item["reason"] = None
        return {"items": items[:limit], "depth": depth}

    def stats(self) -> dict:
        events = self._events()
        splits = self._load_splits()
        ids = self.list_capture_ids()
        counts = {"labeled": 0, "partial": 0, "unlabeled": 0, "excluded": 0}
        by_split = {s: 0 for s in SPLITS}
        distinct_by_split: dict[str, set[str]] = {s: set() for s in SPLITS}
        coverage: list[list[int]] = [[0] * 10 for _ in range(self.digit_count)]
        coverage_by_split = {
            s: [[0] * 10 for _ in range(self.digit_count)] for s in SPLITS
        }
        flag_counts = {f: 0 for f in FLAGS}
        for capture_id in ids:
            labels = self.effective_labels(capture_id, events)
            flags = set(labels["flags"])
            for flag in flags:
                flag_counts[flag] += 1
            if "bad_frame" in flags:
                counts["excluded"] += 1
                continue
            if labels["reading"] or "unreadable" in flags:
                counts["labeled"] += 1
            elif labels["digits"] or flags:
                counts["partial"] += 1
            else:
                counts["unlabeled"] += 1
            split = splits["capture"].get(capture_id)
            if split and (labels["reading"] or labels["digits"]):
                by_split[split] += 1
                if labels["reading"]:
                    distinct_by_split[split].add(labels["reading"])
            for position, digit in labels["digits"].items():
                coverage[int(position)][int(digit)] += 1
                if split:
                    coverage_by_split[split][int(position)][int(digit)] += 1
        return {
            "captures": len(ids),
            **counts,
            "by_split": by_split,
            "distinct_values_by_split": {s: len(v) for s, v in distinct_by_split.items()},
            "coverage": coverage,
            "coverage_by_split": coverage_by_split,
            "flags": flag_counts,
        }

    def import_manifest(self, golden_dir: Path, *, now: datetime | None = None) -> int:
        """Register an existing golden_set manifest as human labels (bootstrap):
        the crops are copied into labeled/ and each entry's split is honored,
        so their value groups are sealed against training/few-shot use."""
        now = now or datetime.now(timezone.utc)
        manifest = json.loads((golden_dir / "manifest.json").read_text(encoding="utf-8"))
        imported = 0
        for entry in manifest:
            capture_id = Path(entry["file"]).stem
            if not CAPTURE_ID_RE.match(capture_id):
                continue
            crop = golden_dir / entry["file"]
            dest = self.labeled_dir / capture_id
            dest.mkdir(parents=True, exist_ok=True)
            if not (dest / "crop.jpg").exists():
                shutil.copy2(crop, dest / "crop.jpg")
            already = self.effective_labels(capture_id)["reading"] == entry["digits"]
            if not already:
                self.add_label(
                    capture_id,
                    "reading",
                    value=entry["digits"],
                    source="golden-import",
                    split=entry.get("split", "verify"),
                    now=now,
                )
                imported += 1
        return imported
