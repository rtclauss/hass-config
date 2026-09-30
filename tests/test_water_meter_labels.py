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


def test_dynamic_pool_keeps_one_example_per_reading_newest_wins(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    old, new, other = tmp_path / "old.jpg", tmp_path / "new.jpg", tmp_path / "other.jpg"
    old.write_bytes(b"old"); new.write_bytes(b"new"); other.write_bytes(b"other")
    labels.append_dynamic_example(pool, old, "02148506", "20260929T045652Z")
    labels.append_dynamic_example(pool, other, "02147700", "20260929T050000Z")
    labels.append_dynamic_example(pool, new, "02148506", "20260929T104130Z")

    index = json.loads((pool / "index.json").read_text())
    assert [e["digits"] for e in index] == ["02147700", "02148506"]
    assert (pool / "20260929T104130Z_02148506.jpg").read_bytes() == b"new"
    assert not (pool / "20260929T045652Z_02148506.jpg").exists()  # superseded image removed


def _jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + sof + b"\xff\xd9"


def test_frames_the_calibration_cannot_apply_to_are_legacy_and_kept_out_of_the_queue(tmp_path: Path) -> None:
    (tmp_path / "cal.json").write_text(json.dumps({"capture_width": 1280, "capture_height": 960}))
    store = _store(tmp_path)
    history = tmp_path / "images" / "history"
    history.mkdir(parents=True)
    fixtures = {
        "20260929T100000Z": _jpeg(1280, 960),  # matches the calibration
        "20260928T100000Z": _jpeg(640, 480),  # other resolution: different field of view
    }
    for cid, raw in fixtures.items():
        (history / f"{cid}_raw.jpg").write_bytes(raw)
        (history / f"{cid}_crop.jpg").write_bytes(b"crop")
    (history / "20260927T100000Z_crop.jpg").write_bytes(b"crop")  # no full frame at all

    assert store.frame_size("20260929T100000Z") == (1280, 960)
    assert not store.is_legacy("20260929T100000Z")
    assert store.is_legacy("20260928T100000Z")
    assert store.is_legacy("20260927T100000Z")
    assert store.item("20260928T100000Z")["frame"] == {"width": 640, "height": 480}

    assert [i["id"] for i in store.queue("queue")["items"]] == ["20260929T100000Z"]
    assert {i["id"] for i in store.queue("legacy")["items"]} == {"20260928T100000Z", "20260927T100000Z"}
    assert len(store.queue("all")["items"]) == 3
    # labeling a legacy frame's reading is still allowed (the reading is valid)
    store.add_label("20260928T100000Z", "reading", value="02147013", now=NOW)
    assert "20260928T100000Z" in [i["id"] for i in store.queue("legacy")["items"]]  # still listed there


def test_without_a_calibration_nothing_is_legacy(tmp_path: Path) -> None:
    store = _store(tmp_path)  # cal.json absent
    _capture(tmp_path, "20260929T100000Z")
    assert store.expected_frame_size() is None
    assert not store.is_legacy("20260929T100000Z")


def test_readings_between_two_equal_human_labels_are_inferred_and_never_queued(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [f"20260929T{h:02d}0000Z" for h in range(8, 14)]
    for cid in ids:
        _capture(tmp_path, cid)
    store.add_label(ids[0], "reading", value="02148506", split="train", now=NOW)
    store.add_label(ids[3], "reading", value="02148506", split="train", now=NOW)
    store.add_label(ids[5], "reading", value="02148528", split="train", now=NOW)
    store.add_label(ids[2], "flag", flag="bad_frame", value=True, now=NOW)  # a human already spoke

    inferred = store.inferred_readings()
    assert inferred == {ids[1]: "02148506"}  # ids[2] is flagged; ids[4] sits between different values
    assert store.item(ids[1])["status"] == "inferred"
    queue_ids = [i["id"] for i in store.queue("queue")["items"]]
    assert ids[1] not in queue_ids and ids[4] in queue_ids
    assert [i["id"] for i in store.queue("inferred")["items"]] == [ids[1]]
    assert store.stats()["inferred"] == 1


def test_a_human_label_overrides_an_inference(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [f"20260929T{h:02d}0000Z" for h in range(8, 11)]
    for cid in ids:
        _capture(tmp_path, cid)
    store.add_label(ids[0], "reading", value="02148506", split="train", now=NOW)
    store.add_label(ids[2], "reading", value="02148506", split="train", now=NOW)
    assert ids[1] in store.inferred_readings()
    store.add_label(ids[1], "digit", position=7, value="6", now=NOW)
    assert ids[1] not in store.inferred_readings()


def _full_capture(tmp_path: Path, cid: str, *, labeled: bool = True, split: str = "train", value: str = "02148506") -> None:
    _capture(tmp_path, cid, guess=value)
    rejects = tmp_path / "images" / "rejects"
    rejects.mkdir(parents=True, exist_ok=True)
    (rejects / f"{cid}_value_decreased.jpg").write_bytes(b"reject")
    if labeled:
        _store(tmp_path).add_label(cid, "reading", value=value, split=split, now=NOW)


def test_delete_moves_everything_to_trash_and_restore_puts_it_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    cid = "20260929T100000Z"
    _full_capture(tmp_path, cid)
    before = sorted(str(p.relative_to(tmp_path / "images")) for p in (tmp_path / "images").rglob("*") if p.is_file())

    assert store.delete_captures([cid], now=NOW) == {"deleted": 1}

    assert cid not in store.list_capture_ids()
    assert store.list_trash_ids() == [cid]
    assert not list((tmp_path / "images" / "history").glob(f"{cid}_*"))
    assert not (tmp_path / "images" / "labeled" / cid).exists()
    assert not list((tmp_path / "images" / "rejects").glob(f"{cid}_*"))
    assert store.trash_item(cid)["labels"]["reading"] == "02148506"  # label survives in the log
    assert store.queue("trash")["items"][0]["id"] == cid
    assert cid not in [i["id"] for i in store.queue("all")["items"]]
    assert store.stats()["captures"] == 0

    store.restore_captures([cid], now=NOW)
    after = sorted(str(p.relative_to(tmp_path / "images")) for p in (tmp_path / "images").rglob("*") if p.is_file())
    assert [a for a in after if not a.startswith("trash")] == [b for b in before if not b.startswith("trash")]
    assert store.list_trash_ids() == []
    assert store.effective_labels(cid)["reading"] == "02148506"


def test_sealed_test_captures_are_refused_unless_explicitly_allowed_and_stay_sealed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    keep, sealed = "20260929T100000Z", "20260929T110000Z"
    _full_capture(tmp_path, keep, split="train", value="02148506")
    _full_capture(tmp_path, sealed, split="test", value="02148528")

    with pytest.raises(LabelError, match="sealed test split"):
        store.delete_captures([keep, sealed], now=NOW)
    assert store.list_trash_ids() == []  # all-or-nothing: the unsealed one was not moved either
    assert {keep, sealed} <= set(store.list_capture_ids())

    store.delete_captures([keep, sealed], allow_sealed=True, now=NOW)
    events = [json.loads(l) for l in store.events_path.read_text().splitlines() if '"delete"' in l]
    assert [e["allow_sealed"] for e in events] == [False, True]  # the override is audited
    assert store.value_split("02148528") == "test"  # the value can never turn into training data


def test_purge_only_touches_the_trash_and_deleted_anchors_stop_inferring(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [f"20260929T{h:02d}0000Z" for h in (8, 9, 10)]
    for cid in ids:
        _capture(tmp_path, cid)
    store.add_label(ids[0], "reading", value="02148506", split="train", now=NOW)
    store.add_label(ids[2], "reading", value="02148506", split="train", now=NOW)
    assert store.inferred_readings() == {ids[1]: "02148506"}

    with pytest.raises(LabelError, match="not in the trash"):
        store.purge_captures([ids[1]])
    store.delete_captures([ids[2]], now=NOW)  # an anchor is deleted (maybe it was mislabeled)
    assert store.inferred_readings() == {}

    store.purge_captures([ids[2]], now=NOW)
    assert store.list_trash_ids() == []
    with pytest.raises(LabelError, match="not in the trash"):
        store.restore_captures([ids[2]])


def test_delete_rejects_unknown_and_malformed_ids_without_partial_effects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _full_capture(tmp_path, "20260929T100000Z", labeled=False)
    for bad in ("../x", "nope", "20260101T000000Z"):
        with pytest.raises(LabelError):
            store.delete_captures(["20260929T100000Z", bad], now=NOW)
    assert store.list_trash_ids() == [] and "20260929T100000Z" in store.list_capture_ids()
