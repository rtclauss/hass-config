from __future__ import annotations

import json
from pathlib import Path

import pytest

from water_meter import eval as water_meter_eval
from water_meter import ocr


def _make_golden_set(tmp_path: Path) -> Path:
    golden_dir = tmp_path / "golden_set"
    golden_dir.mkdir()
    (golden_dir / "a.jpg").write_bytes(b"image-a")
    (golden_dir / "b.jpg").write_bytes(b"image-b")
    manifest = [
        {"file": "a.jpg", "digits": "02148452", "capture_width": 1280, "capture_height": 960},
        {"file": "b.jpg", "digits": "02147941", "capture_width": 1280, "capture_height": 960},
    ]
    (golden_dir / "manifest.json").write_text(json.dumps(manifest))
    return golden_dir


def test_load_golden_set_reads_the_manifest(tmp_path: Path) -> None:
    golden_dir = _make_golden_set(tmp_path)

    examples = water_meter_eval.load_golden_set(golden_dir)

    assert len(examples) == 2
    assert examples[0].file == "a.jpg"
    assert examples[0].digits == "02148452"
    assert examples[0].capture_width == 1280


def test_the_repos_own_golden_set_manifest_matches_its_image_files() -> None:
    # Guards against a manifest entry pointing at a deleted/renamed file, or
    # an image dropped without updating the manifest - either would make
    # `eval run` fail confusingly mid-run instead of at load time.
    examples = water_meter_eval.load_golden_set()
    assert len(examples) >= 10  # a real regression suite, not a stub
    for example in examples:
        path = water_meter_eval.GOLDEN_SET_DIR / example.file
        assert path.exists(), f"golden_set manifest references missing file {example.file}"
        assert example.digits.isdigit()


def test_run_eval_scores_exact_matches_and_records_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden_dir = _make_golden_set(tmp_path)

    def _fake_read_digits_vlm(image_path: Path, **kwargs: object) -> str:
        # Get "a.jpg" right, "b.jpg" wrong.
        return "02148452" if image_path.name == "a.jpg" else "00000000"

    monkeypatch.setattr(ocr, "read_digits_vlm", _fake_read_digits_vlm)

    run = water_meter_eval.run_eval(
        host="fake-host:1234", model="fake-model", label="test-run", golden_dir=golden_dir, progress=False
    )

    assert run.n == 2
    assert run.exact_match_count == 1
    assert run.exact_match_rate == 0.5
    assert run.error_count == 0
    assert all(r.seconds >= 0 for r in run.results)


def test_run_eval_records_ocr_errors_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden_dir = _make_golden_set(tmp_path)

    def _always_fails(image_path: Path, **kwargs: object) -> str:
        raise ocr.OcrError("vision-LLM request failed: connection refused")

    monkeypatch.setattr(ocr, "read_digits_vlm", _always_fails)

    run = water_meter_eval.run_eval(
        host="fake-host:1234", model="fake-model", label="test-run", golden_dir=golden_dir, progress=False
    )

    assert run.n == 2
    assert run.exact_match_count == 0
    assert run.error_count == 2
    assert all(r.predicted is None for r in run.results)
    assert all(r.error is not None for r in run.results)


def test_run_eval_forwards_dynamic_examples_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden_dir = _make_golden_set(tmp_path)
    examples_dir = tmp_path / "human_corrections"
    captured: dict = {}

    def _fake_read_digits_vlm(image_path: Path, **kwargs: object) -> str:
        captured["dynamic_examples_dir"] = kwargs.get("dynamic_examples_dir")
        return "02148452"

    monkeypatch.setattr(ocr, "read_digits_vlm", _fake_read_digits_vlm)

    water_meter_eval.run_eval(
        host="fake-host:1234",
        model="fake-model",
        label="test-run",
        golden_dir=golden_dir,
        dynamic_examples_dir=examples_dir,
        progress=False,
    )

    assert captured["dynamic_examples_dir"] == examples_dir


def test_save_and_load_eval_run_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_dir = _make_golden_set(tmp_path)
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda image_path, **kwargs: "02148452")

    run = water_meter_eval.run_eval(
        host="fake-host:1234", model="fake-model", label="round-trip", golden_dir=golden_dir, progress=False
    )
    path = water_meter_eval.save_eval_run(run, results_dir=tmp_path / "results")
    assert path.exists()

    loaded = water_meter_eval.load_eval_run(path)
    assert loaded.label == run.label
    assert loaded.model == run.model
    assert loaded.exact_match_count == run.exact_match_count
    assert [r.file for r in loaded.results] == [r.file for r in run.results]


def test_compare_runs_identifies_regressions_and_improvements() -> None:
    baseline = water_meter_eval.EvalRun(
        label="baseline",
        model="model-a",
        host="host",
        timestamp="2026-09-28T00:00:00+00:00",
        dynamic_examples_dir=None,
        results=[
            water_meter_eval.ExampleResult("a.jpg", "111", "111", True, 1.0),
            water_meter_eval.ExampleResult("b.jpg", "222", "999", False, 1.0),
        ],
    )
    candidate = water_meter_eval.EvalRun(
        label="candidate",
        model="model-b",
        host="host",
        timestamp="2026-09-28T01:00:00+00:00",
        dynamic_examples_dir=None,
        results=[
            water_meter_eval.ExampleResult("a.jpg", "111", "888", False, 2.0),  # regressed
            water_meter_eval.ExampleResult("b.jpg", "222", "222", True, 2.0),  # improved
        ],
    )

    report = water_meter_eval.compare_runs(baseline, candidate)

    assert "REGRESSIONS (1)" in report
    assert "a.jpg" in report
    assert "IMPROVEMENTS (1)" in report
    assert "b.jpg" in report
    assert "+1.0s" in report


def test_compare_runs_reports_no_regressions_cleanly() -> None:
    baseline = water_meter_eval.EvalRun(
        label="baseline",
        model="model-a",
        host="host",
        timestamp="2026-09-28T00:00:00+00:00",
        dynamic_examples_dir=None,
        results=[water_meter_eval.ExampleResult("a.jpg", "111", "111", True, 1.0)],
    )
    candidate = water_meter_eval.EvalRun(
        label="candidate",
        model="model-b",
        host="host",
        timestamp="2026-09-28T01:00:00+00:00",
        dynamic_examples_dir=None,
        results=[water_meter_eval.ExampleResult("a.jpg", "111", "111", True, 1.0)],
    )

    report = water_meter_eval.compare_runs(baseline, candidate)

    assert "No regressions." in report
