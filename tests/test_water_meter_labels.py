from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from water_meter import labels
from water_meter.labels import LabelError, LabelStore

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> LabelStore:
    return LabelStore(tmp_path / "images", tmp_path / "state", calibration_path=tmp_path / "cal.json")


def _capture(
    tmp_path: Path,
    capture_id: str,
    *,
    guess: str | None = None,
    accepted: bool = True,
    digits: bool = True,
) -> None:
    history = tmp_path / "images" / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / f"{capture_id}_crop.jpg").write_bytes(b"crop-" + capture_id.encode())
    (history / f"{capture_id}_raw.jpg").write_bytes(b"raw-" + capture_id.encode())
    if digits:
        for i in range(8):
            (history / f"{capture_id}_digit{i}.jpg").write_bytes(b"d%d" % i)
    if guess is not None:
        (history / f"{capture_id}_read.json").write_text(
            json.dumps({"raw_digits": guess, "accepted": accepted, "reason": "ok" if accepted else "value decreased"})
        )


def test_add_reading_snapshots_files_that_survive_history_rotation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (tmp_path / "cal.json").write_text("{}")
    _capture(tmp_path, "20260929T100000Z", guess="02147013")

    store.add_label("20260929T100000Z", "reading", value="02147013", now=NOW)
    for path in (tmp_path / "images" / "history").glob("*"):
        path.unlink()  # history rotates the capture away

    files = store.capture_files("20260929T100000Z")
    assert {"raw", "crop", "digit0", "digit7", "read"} <= set(files)
    assert (tmp_path / "images" / "labeled" / "20260929T100000Z" / "calibration.json").exists()
    assert store.effective_labels("20260929T100000Z")["reading"] == "02147013"


def test_reading_must_be_exactly_the_digit_count_and_ids_are_validated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260929T100000Z")
    with pytest.raises(LabelError, match="8 digits"):
        store.add_label("20260929T100000Z", "reading", value="123")
    with pytest.raises(LabelError, match="8 digits"):
        store.add_label("20260929T100000Z", "reading", value="1234567x")
    for bad in ("../etc/passwd", "20260929T100000Z/../x", "nope", ""):
        with pytest.raises(LabelError):
            store.add_label(bad, "reading", value="02147013")
    with pytest.raises(LabelError, match="unknown capture"):
        store.add_label("20260101T000000Z", "reading", value="02147013")


def test_digit_labels_override_a_reading_and_partial_digits_have_no_reading(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260929T100000Z")
    store.add_label("20260929T100000Z", "digit", position=4, value="7", now=NOW)
    partial = store.effective_labels("20260929T100000Z")
    assert partial["reading"] is None
    assert partial["digits"] == {"4": "7"}

    store.add_label("20260929T100000Z", "reading", value="02141234", now=NOW)
    store.add_label("20260929T100000Z", "digit", position=4, value="7", now=NOW)
    assert store.effective_labels("20260929T100000Z")["reading"] == "02147234"


def test_flags_toggle_and_unreadable_counts_as_labeled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260929T100000Z")
    item = store.add_label("20260929T100000Z", "flag", flag="unreadable", value=True, now=NOW)
    assert item["labels"]["flags"] == ["unreadable"]
    assert item["status"] == "labeled"
    item = store.add_label("20260929T100000Z", "flag", flag="unreadable", value=False, now=NOW)
    assert item["labels"]["flags"] == []
    with pytest.raises(LabelError):
        store.add_label("20260929T100000Z", "flag", flag="bogus", value=True)


def test_value_groups_share_a_split_and_splits_only_move_toward_sealed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for capture_id in ("20260901T000000Z", "20260901T010000Z", "20260901T020000Z"):
        _capture(tmp_path, capture_id)

    a = store.add_label("20260901T000000Z", "reading", value="02147013", now=NOW, split="train")
    b = store.add_label("20260901T010000Z", "reading", value="02147013", now=NOW)
    assert a["split"] == b["split"] == "train"  # same value group, same split

    # Sealing the group via one capture promotes every sibling...
    store.add_label("20260901T020000Z", "reading", value="02147013", now=NOW, split="test")
    assert store.split_of("20260901T000000Z") == "test"
    assert store.value_split("02147013") == "test"
    # ...and asking for a less sealed split never demotes it.
    store.add_label("20260901T000000Z", "reading", value="02147013", now=NOW, split="train")
    assert store.split_of("20260901T000000Z") == "test"
    events = [json.loads(l) for l in store.events_path.read_text().splitlines()]
    assert any(e["kind"] == "split" for e in events)  # promotion is audited


def _id_at(hours: float) -> str:
    return (labels.SCHEDULE_EPOCH + timedelta(hours=hours)).strftime("%Y%m%dT%H%M%SZ")


def test_schedule_has_the_advertised_proportions_and_isolated_eval_blocks() -> None:
    schedule = labels.SCHEDULE
    assert len(schedule) == 20
    assert schedule.count("T") == 14 and schedule.count("V") == 3 and schedule.count("E") == 3
    for i, kind in enumerate(schedule):
        if kind != "T":
            assert schedule[(i - 1) % 20] == "T" and schedule[(i + 1) % 20] == "T", i


def test_scheduled_split_is_deterministic_and_follows_time_blocks() -> None:
    block_hours = labels.BLOCK_SECONDS / 3600
    # middle of each block of one full cycle
    splits = [labels.scheduled_split(_id_at((b + 0.5) * block_hours)) for b in range(20)]
    assert splits == [
        {"T": "train", "V": "verify", "E": "test"}[k] for k in labels.SCHEDULE
    ]
    assert labels.scheduled_split(_id_at(5.5 * block_hours)) == labels.scheduled_split(_id_at(5.5 * block_hours))
    # over a long span the shares approach 70/15/15
    counts = {"train": 0, "embargo": 0, "verify": 0, "test": 0}
    for hour in range(0, 24 * 60):
        counts[labels.scheduled_split(_id_at(hour + 0.25))] += 1
    total = sum(counts.values())
    assert 0.12 < counts["test"] / total < 0.18
    assert 0.12 < counts["verify"] / total < 0.18
    assert counts["embargo"] > 0 and counts["train"] / total > 0.55


def test_train_captures_next_to_an_eval_block_are_embargoed() -> None:
    block_hours = labels.BLOCK_SECONDS / 3600
    test_block = labels.SCHEDULE.index("E")
    # start of the train block right after the test block, and its far end
    just_after = _id_at((test_block + 1) * block_hours + 0.1)
    far_from_eval = _id_at((test_block + 1) * block_hours + block_hours / 2)
    just_before = _id_at(test_block * block_hours - 0.1)
    assert labels.scheduled_split(just_after) == "embargo"
    assert labels.scheduled_split(just_before) == "embargo"
    assert labels.scheduled_split(far_from_eval) == "train"


def test_first_label_uses_the_schedule_and_digit_only_labels_follow_their_time_block(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    block_hours = labels.BLOCK_SECONDS / 3600
    test_id = _id_at((labels.SCHEDULE.index("E") + 0.5) * block_hours)
    train_id = _id_at((labels.SCHEDULE.index("T") + 0.5) * block_hours)
    _capture(tmp_path, test_id)
    _capture(tmp_path, train_id)

    assert store.add_label(test_id, "digit", position=4, value="7", now=NOW)["split"] == "test"
    assert store.add_label(train_id, "reading", value="02147013", now=NOW)["split"] == "train"


def test_train_split_readings_feed_the_dynamic_pool_but_eval_splits_do_not(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260901T000000Z")
    _capture(tmp_path, "20260901T010000Z")

    store.add_label("20260901T000000Z", "reading", value="02147013", now=NOW, split="train")
    store.add_label("20260901T010000Z", "reading", value="02147134", now=NOW, split="verify")

    index = json.loads((tmp_path / "images" / "human_corrections" / "index.json").read_text())
    assert [e["digits"] for e in index] == ["02147013"]


def test_append_dynamic_example_caps_the_pool_and_deletes_old_images(tmp_path: Path) -> None:
    crop = tmp_path / "crop.jpg"
    crop.write_bytes(b"img")
    pool = tmp_path / "pool"
    for n in range(4):
        labels.append_dynamic_example(pool, crop, f"0000000{n}", f"2026090{n}T000000Z", limit=2)
    index = json.loads((pool / "index.json").read_text())
    assert [e["digits"] for e in index] == ["00000002", "00000003"]
    assert len(list(pool.glob("*.jpg"))) == 2
    assert not labels.append_dynamic_example(pool, tmp_path / "missing.jpg", "1", "x")


def test_queue_puts_rejects_first_then_diverse_values_and_hides_labeled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260929T010000Z", guess="02147013")
    _capture(tmp_path, "20260929T020000Z", guess="02147013")  # same guess as above
    _capture(tmp_path, "20260929T030000Z", guess="02147134")
    _capture(tmp_path, "20260929T040000Z", guess="02140000", accepted=False)
    _capture(tmp_path, "20260929T050000Z", guess="02147200")
    store.add_label("20260929T050000Z", "reading", value="02147200", now=NOW)

    queue = store.queue("queue")
    ids = [i["id"] for i in queue["items"]]
    assert ids[0] == "20260929T040000Z"  # rejected first
    assert "20260929T050000Z" not in ids  # already labeled
    # diverse: one capture per guessed value before the duplicate
    assert ids.index("20260929T030000Z") < ids.index("20260929T010000Z")
    assert ids[-1] == "20260929T010000Z"
    assert queue["depth"] == 4
    assert [i["id"] for i in store.queue("labeled")["items"]] == ["20260929T050000Z"]
    assert len(store.queue("all")["items"]) == 5


def test_blind_mode_hides_guess_and_reason(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260929T010000Z", guess="02147013", accepted=False)
    assert store.item("20260929T010000Z")["guess"] == "02147013"
    blind = store.item("20260929T010000Z", blind=True)
    assert blind["guess"] is None and blind["reason"] is None
    q = store.queue("queue", blind=True)["items"][0]
    assert q["guess"] is None and q["reason"] is None


def test_stats_reports_split_counts_distinct_values_and_digit_coverage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(tmp_path, "20260901T000000Z")
    _capture(tmp_path, "20260901T010000Z")
    _capture(tmp_path, "20260901T020000Z")
    store.add_label("20260901T000000Z", "reading", value="02147013", now=NOW, split="test")
    store.add_label("20260901T010000Z", "reading", value="02147013", now=NOW)
    store.add_label("20260901T020000Z", "digit", position=4, value="8", now=NOW)

    stats = store.stats()
    assert stats["captures"] == 3
    assert stats["labeled"] == 2 and stats["partial"] == 1
    assert stats["by_split"]["test"] == 2
    assert stats["distinct_values_by_split"]["test"] == 1
    assert stats["coverage"][4][7] == 2 and stats["coverage"][4][8] == 1


def test_import_manifest_seals_value_groups_and_is_idempotent(tmp_path: Path) -> None:
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "20260926T045114Z.jpg").write_bytes(b"crop")
    (golden / "manifest.json").write_text(
        json.dumps([{"file": "20260926T045114Z.jpg", "digits": "02146964", "split": "verify"}])
    )
    store = _store(tmp_path)

    assert store.import_manifest(golden, now=NOW) == 1
    assert store.import_manifest(golden, now=NOW) == 0
    assert store.value_split("02146964") == "verify"
    assert store.effective_labels("20260926T045114Z")["reading"] == "02146964"
    # a later capture of the same value can never land in train
    _capture(tmp_path, "20260929T100000Z")
    later = store.add_label("20260929T100000Z", "reading", value="02146964", now=NOW, split="train")
    assert later["split"] == "verify"
    assert not (tmp_path / "images" / "human_corrections" / "index.json").exists()
