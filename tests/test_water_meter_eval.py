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


def test_wilson_ci_is_honest_at_small_n() -> None:
    low, high = water_meter_eval.wilson_ci(0, 15)
    assert low == 0.0
    assert 0.15 < high < 0.25  # 0/15 is still compatible with ~20%
    assert water_meter_eval.wilson_ci(0, 0) == (0.0, 0.0)


def test_mcnemar_p_matches_known_values() -> None:
    assert water_meter_eval.mcnemar_p(0, 0) == 1.0
    assert water_meter_eval.mcnemar_p(5, 5) == 1.0
    # 0 vs 8 discordant pairs: 2 * (1/2)^8
    assert water_meter_eval.mcnemar_p(0, 8) == pytest.approx(2 / 256)


def _run_with(results: list[tuple[str, str, str | None]], leaked: list[str] | None = None):
    return water_meter_eval.EvalRun(
        label="x",
        model="m",
        host="h",
        timestamp="2026-09-29T00:00:00+00:00",
        dynamic_examples_dir=None,
        leaked_files=leaked or [],
        results=[
            water_meter_eval.ExampleResult(f, exp, pred, pred == exp, 1.0, None if pred else "boom")
            for f, exp, pred in results
        ],
    )


def test_per_position_accuracy_and_confusions() -> None:
    run = _run_with(
        [
            ("a", "1234", "1234"),
            ("b", "1274", "1214"),  # index 2: 7 -> 1
            ("c", "1274", "1214"),  # again
            ("d", "1234", None),  # hard error: wrong everywhere
        ]
    )
    assert run.per_position_accuracy() == [0.75, 0.75, 0.25, 0.75]
    assert run.confusions()[("7", "1")] == 2


def test_leaked_examples_are_reported_separately() -> None:
    run = _run_with([("a", "111", "111"), ("b", "222", "999")], leaked=["a"])
    assert run.clean_exact_match_count == 0
    assert len(run.clean_results) == 1
    summary = water_meter_eval.format_summary(run)
    assert "share a value with the few-shot examples" in summary


def test_run_eval_flags_values_shared_with_static_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden_dir = tmp_path / "g"
    golden_dir.mkdir()
    (golden_dir / "a.jpg").write_bytes(b"a")
    shared_value = ocr.VLM_FEWSHOT_EXAMPLES[0][1]
    (golden_dir / "manifest.json").write_text(
        json.dumps([{"file": "a.jpg", "digits": shared_value, "split": "verify"}])
    )
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda p, **k: shared_value)

    run = water_meter_eval.run_eval(
        host="h", model="m", label="l", golden_dir=golden_dir, progress=False
    )
    assert run.leaked_files == ["a.jpg"]

    with pytest.raises(water_meter_eval.EvalError, match="share a value"):
        water_meter_eval.run_eval(
            host="h", model="m", label="l", golden_dir=golden_dir, strict_leakage=True, progress=False
        )


def _split_set(tmp_path: Path) -> Path:
    golden_dir = tmp_path / "g"
    golden_dir.mkdir()
    (golden_dir / "v.jpg").write_bytes(b"v")
    (golden_dir / "t.jpg").write_bytes(b"t")
    (golden_dir / "manifest.json").write_text(
        json.dumps(
            [
                {"file": "v.jpg", "digits": "02140001", "split": "verify"},
                {"file": "t.jpg", "digits": "02140002", "split": "test"},
            ]
        )
    )
    return golden_dir


def test_test_split_is_sealed_without_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_dir = _split_set(tmp_path)
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda p, **k: "02140001")

    with pytest.raises(water_meter_eval.EvalError, match="sealed"):
        water_meter_eval.run_eval(
            host="h", model="m", label="l", golden_dir=golden_dir, split="test", progress=False
        )
    with pytest.raises(water_meter_eval.EvalError, match="sealed"):
        water_meter_eval.run_eval(
            host="h", model="m", label="l", golden_dir=golden_dir, split="all", progress=False
        )


def test_verify_split_excludes_test_items_and_test_runs_are_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden_dir = _split_set(tmp_path)
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda p, **k: "02140001")

    verify = water_meter_eval.run_eval(
        host="h", model="m", label="l", golden_dir=golden_dir, progress=False
    )
    assert [r.file for r in verify.results] == ["v.jpg"]

    final = water_meter_eval.run_eval(
        host="h", model="m", label="final", golden_dir=golden_dir, split="test", final=True, progress=False
    )
    assert [r.file for r in final.results] == ["t.jpg"]

    results_dir = tmp_path / "results"
    water_meter_eval.save_eval_run(verify, results_dir)
    assert not (results_dir / water_meter_eval.TEST_RUNS_LOG).exists()
    water_meter_eval.save_eval_run(final, results_dir)
    log_lines = (results_dir / water_meter_eval.TEST_RUNS_LOG).read_text().splitlines()
    assert len(log_lines) == 1
    assert json.loads(log_lines[0])["label"] == "final"


def test_tampered_eval_image_is_rejected(tmp_path: Path) -> None:
    golden_dir = tmp_path / "g"
    golden_dir.mkdir()
    (golden_dir / "a.jpg").write_bytes(b"original")
    digest = water_meter_eval.file_sha256(golden_dir / "a.jpg")
    (golden_dir / "manifest.json").write_text(
        json.dumps([{"file": "a.jpg", "digits": "1", "sha256": digest}])
    )
    assert len(water_meter_eval.load_golden_set(golden_dir)) == 1

    (golden_dir / "a.jpg").write_bytes(b"tampered")
    with pytest.raises(water_meter_eval.EvalError, match="sha256"):
        water_meter_eval.load_golden_set(golden_dir)


def test_repos_golden_set_is_sealed_with_hashes_and_splits() -> None:
    examples = water_meter_eval.load_golden_set()  # verifies every sha256
    assert all(e.sha256 for e in examples)
    assert {e.split for e in examples} <= set(water_meter_eval.SPLITS)


def test_collect_provenance_records_versions_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Resp:
        def __init__(self, body: dict) -> None:
            self._body = json.dumps(body).encode()

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _fake_urlopen(request: object, timeout: float = 0) -> _Resp:
        url = request if isinstance(request, str) else request.full_url  # type: ignore[attr-defined]
        if url.endswith("/api/version"):
            return _Resp({"version": "0.34.4"})
        return _Resp({"details": {"digest": "abc123", "family": "qwen25vl"}})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    info = water_meter_eval.collect_provenance(
        host="h", model="m", digit_count=8, dynamic_examples_dir=None
    )

    assert info["ollama_version"] == "0.34.4"
    assert info["model_digest"] == "abc123"
    assert len(info["prompt_sha256"]) == 16
    assert len(info["examples_sha256"]) == 16
    assert info["temperature"] == 0


def test_value_weighted_rate_counts_near_duplicates_once() -> None:
    run = _run_with(
        [("a1", "111", "111"), ("a2", "111", "111"), ("a3", "111", "111"), ("b", "222", "999")]
    )
    groups, weighted = run.value_weighted()
    assert groups == 2 and weighted == 0.5  # 3 right copies of one value + 1 wrong value
    assert run.exact_match_rate == 0.75  # the raw rate flatters it
    assert "only 2 distinct values among 4 captures" in water_meter_eval.format_summary(run)
