"""Regression/comparison harness for the VLM OCR tier.

Every round of model/prompt comparison in this project so far (see the
"Reading Through Glare" report) was a one-off ad hoc script, run once,
discarded, and reconstructed from scratch next time - including a real
resolution A/B test that had to be redesigned twice after a methodology
mistake, purely because there was no reusable harness enforcing a consistent,
already-solved approach. This module fixes that: a versioned example set
(water_meter/golden_set/, visually-verified real captures) plus a runner that
scores any model/prompt/dynamic-examples combination against it the same way
every time, and a diff tool to compare two runs directly.

Examples carry a split. "verify" is for tuning (prompt/example choice,
thresholds) and may be run freely; "test" is the sealed, golden set for final
numbers and regression watch - it only runs with --final and every run is
appended to eval_results/test_runs.jsonl, so peeking is visible. Selecting
prompts against the test split would overfit it.

Saved results (eval_results/*.json) are meant to be committed to git - the
whole point is a durable, greppable history of "what did we try and what
happened", not a scratch file that gets overwritten.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from math import comb, sqrt
from pathlib import Path
import time

from . import ocr

GOLDEN_SET_DIR = Path(__file__).parent / "golden_set"
EVAL_RESULTS_DIR = Path(__file__).parent / "eval_results"
TEST_RUNS_LOG = "test_runs.jsonl"
SPLITS = ("verify", "test")


class EvalError(RuntimeError):
    """Raised for harness misuse (test split without --final, tampered data)."""


@dataclass(frozen=True)
class GoldenExample:
    file: str
    digits: str
    capture_width: int = 0
    capture_height: int = 0
    split: str = "verify"
    sha256: str = ""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_golden_set(
    golden_dir: Path = GOLDEN_SET_DIR, *, check_hashes: bool = True
) -> list[GoldenExample]:
    manifest = json.loads((golden_dir / "manifest.json").read_text(encoding="utf-8"))
    examples = []
    for entry in manifest:
        example = GoldenExample(
            file=entry["file"],
            digits=entry["digits"],
            capture_width=int(entry.get("capture_width", 0)),
            capture_height=int(entry.get("capture_height", 0)),
            split=entry.get("split", "verify"),
            sha256=entry.get("sha256", ""),
        )
        if example.split not in SPLITS:
            raise EvalError(f"{example.file}: unknown split {example.split!r}")
        if check_hashes and example.sha256:
            actual = file_sha256(golden_dir / example.file)
            if actual != example.sha256:
                raise EvalError(
                    f"{example.file} does not match its manifest sha256 - the sealed "
                    "eval image was modified"
                )
        examples.append(example)
    return examples


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval - honest at the small n this project has."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    margin = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))


def mcnemar_p(baseline_only: int, candidate_only: int) -> float:
    """Exact two-sided McNemar p-value on the discordant pairs.

    baseline_only: files the baseline got right and the candidate got wrong;
    candidate_only: the reverse. Concordant pairs carry no information about
    which config is better, so they are ignored.
    """
    n = baseline_only + candidate_only
    if n == 0:
        return 1.0
    k = min(baseline_only, candidate_only)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


@dataclass
class ExampleResult:
    file: str
    expected: str
    predicted: str | None
    exact_match: bool
    seconds: float
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "expected": self.expected,
            "predicted": self.predicted,
            "exact_match": self.exact_match,
            "seconds": round(self.seconds, 2),
            "error": self.error,
        }


@dataclass
class EvalRun:
    label: str
    model: str
    host: str
    timestamp: str
    dynamic_examples_dir: str | None
    results: list[ExampleResult] = field(default_factory=list)
    split: str = "verify"
    provenance: dict = field(default_factory=dict)
    leaked_files: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def exact_match_count(self) -> int:
        return sum(1 for r in self.results if r.exact_match)

    @property
    def exact_match_rate(self) -> float:
        return self.exact_match_count / self.n if self.n else 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.error is not None)

    @property
    def avg_seconds(self) -> float:
        return sum(r.seconds for r in self.results) / self.n if self.n else 0.0

    @property
    def clean_results(self) -> list[ExampleResult]:
        leaked = set(self.leaked_files)
        return [r for r in self.results if r.file not in leaked]

    @property
    def clean_exact_match_count(self) -> int:
        return sum(1 for r in self.clean_results if r.exact_match)

    def per_position_accuracy(self) -> list[float]:
        """Fraction correct at each digit index; a hard error counts as wrong."""
        width = max((len(r.expected) for r in self.results), default=0)
        accuracy = []
        for i in range(width):
            correct = sum(
                1
                for r in self.results
                if r.predicted is not None
                and len(r.predicted) == len(r.expected)
                and r.predicted[i] == r.expected[i]
            )
            accuracy.append(correct / self.n if self.n else 0.0)
        return accuracy

    def confusions(self) -> Counter:
        """Counter of (expected digit, predicted digit) for every wrong position."""
        counts: Counter = Counter()
        for r in self.results:
            if r.predicted is None or len(r.predicted) != len(r.expected):
                continue
            for expected_digit, predicted_digit in zip(r.expected, r.predicted):
                if expected_digit != predicted_digit:
                    counts[(expected_digit, predicted_digit)] += 1
        return counts

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "model": self.model,
            "host": self.host,
            "timestamp": self.timestamp,
            "split": self.split,
            "dynamic_examples_dir": self.dynamic_examples_dir,
            "provenance": self.provenance,
            "leaked_files": self.leaked_files,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvalRun":
        return cls(
            label=data["label"],
            model=data["model"],
            host=data["host"],
            timestamp=data["timestamp"],
            dynamic_examples_dir=data.get("dynamic_examples_dir"),
            split=data.get("split", "verify"),
            provenance=data.get("provenance", {}),
            leaked_files=data.get("leaked_files", []),
            results=[
                ExampleResult(
                    file=r["file"],
                    expected=r["expected"],
                    predicted=r["predicted"],
                    exact_match=r["exact_match"],
                    seconds=r["seconds"],
                    error=r.get("error"),
                )
                for r in data["results"]
            ],
        )


def collect_provenance(
    *,
    host: str,
    model: str,
    digit_count: int,
    dynamic_examples_dir: Path | None,
    timeout: float = 10.0,
) -> dict:
    """Record what actually produced a result: without this a score can't be
    attributed to a model build, prompt or example set after the fact."""
    import urllib.error
    import urllib.request

    info: dict = {}
    try:
        with urllib.request.urlopen(f"http://{host}/api/version", timeout=timeout) as response:
            info["ollama_version"] = json.loads(response.read()).get("version")
    except (urllib.error.URLError, OSError, ValueError):
        info["ollama_version"] = None
    try:
        request = urllib.request.Request(
            f"http://{host}/api/show",
            data=json.dumps({"name": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            details = json.loads(response.read())
        info["model_digest"] = (details.get("details") or {}).get("digest") or details.get("digest")
        info["model_details"] = details.get("details")
    except (urllib.error.URLError, OSError, ValueError):
        info["model_digest"] = None

    dynamic = ocr.load_dynamic_examples(dynamic_examples_dir)
    info["prompt_sha256"] = hashlib.sha256(
        ocr._build_vlm_fewshot_prompt(digit_count, dynamic).encode("utf-8")
    ).hexdigest()[:16]
    hasher = hashlib.sha256()
    for filename, reading in ocr.VLM_FEWSHOT_EXAMPLES:
        hasher.update(reading.encode())
        hasher.update((ocr.VLM_EXAMPLES_DIR / filename).read_bytes())
    for path, reading in dynamic:
        hasher.update(reading.encode())
        hasher.update(path.read_bytes())
    info["examples_sha256"] = hasher.hexdigest()[:16]
    info["temperature"] = ocr.VLM_TEMPERATURE
    info["seed"] = ocr.VLM_SEED
    return info


def example_values(dynamic_examples_dir: Path | None) -> set[str]:
    """Readings the model is shown as examples - eval items sharing one of
    these values are effectively answer-leaked, so they are flagged."""
    values = {reading for _, reading in ocr.VLM_FEWSHOT_EXAMPLES}
    values.update(reading for _, reading in ocr.load_dynamic_examples(dynamic_examples_dir))
    return values


def run_eval(
    *,
    host: str,
    model: str,
    label: str,
    golden_dir: Path = GOLDEN_SET_DIR,
    timeout: float = 480.0,
    dynamic_examples_dir: Path | None = None,
    split: str = "verify",
    final: bool = False,
    strict_leakage: bool = False,
    collect_provenance_info: bool = False,
    progress: bool = True,
) -> EvalRun:
    """Run one model/config against a split of the example set.

    Deliberately calls ocr.read_digits_vlm directly (not ocr.read_digits) -
    this harness measures the VLM tier itself, not the full ssocr-first
    fallback chain, since ssocr essentially never succeeds on this meter
    (0/16 in the report's own three-way comparison) and would just add
    constant, uninteresting overhead to every run.
    """
    if split not in (*SPLITS, "all"):
        raise EvalError(f"unknown split {split!r}")
    if split in ("test", "all") and not final:
        raise EvalError(
            "the test split is sealed: run with final=True (--final) for final numbers or "
            "regression watch, not for tuning - tune on the verify split"
        )
    examples = [
        e
        for e in load_golden_set(golden_dir)
        if split == "all" or e.split == split
    ]
    if not examples:
        raise EvalError(f"no examples in split {split!r}")

    leak_values = example_values(dynamic_examples_dir)
    leaked = [e.file for e in examples if e.digits in leak_values]
    if leaked and strict_leakage:
        raise EvalError(
            f"{len(leaked)} eval example(s) share a value with the few-shot examples: "
            + ", ".join(leaked)
        )

    run = EvalRun(
        label=label,
        model=model,
        host=host,
        timestamp=datetime.now(timezone.utc).isoformat(),
        dynamic_examples_dir=str(dynamic_examples_dir) if dynamic_examples_dir else None,
        split=split,
        leaked_files=leaked,
    )
    if collect_provenance_info:
        run.provenance = collect_provenance(
            host=host,
            model=model,
            digit_count=len(examples[0].digits),
            dynamic_examples_dir=dynamic_examples_dir,
        )

    for i, example in enumerate(examples, 1):
        image_path = golden_dir / example.file
        t0 = time.monotonic()
        predicted: str | None = None
        error: str | None = None
        try:
            predicted = ocr.read_digits_vlm(
                image_path,
                host=host,
                digit_count=len(example.digits),
                model=model,
                timeout=timeout,
                dynamic_examples_dir=dynamic_examples_dir,
            )
        except ocr.OcrError as exc:
            error = str(exc)
        elapsed = time.monotonic() - t0
        exact_match = predicted == example.digits
        run.results.append(
            ExampleResult(
                file=example.file,
                expected=example.digits,
                predicted=predicted,
                exact_match=exact_match,
                seconds=elapsed,
                error=error,
            )
        )
        if progress:
            mark = "OK" if exact_match else ("ERR" if error else "MISS")
            note = " (value shared with an example)" if example.file in leaked else ""
            print(
                f"[{i}/{len(examples)}] {example.file}: {predicted!r} "
                f"(expected {example.digits!r}) {mark} {elapsed:.1f}s{note}",
                flush=True,
            )
    return run


def save_eval_run(run: EvalRun, results_dir: Path = EVAL_RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = run.timestamp.replace(":", "").replace("-", "").split(".")[0].split("+")[0]
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in run.label)
    path = results_dir / f"{stamp}_{safe_label}.json"
    path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
    if run.split in ("test", "all"):
        with (results_dir / TEST_RUNS_LOG).open("a", encoding="utf-8") as log:
            log.write(
                json.dumps(
                    {
                        "timestamp": run.timestamp,
                        "label": run.label,
                        "model": run.model,
                        "exact": f"{run.exact_match_count}/{run.n}",
                        "file": path.name,
                    }
                )
                + "\n"
            )
    return path


def load_eval_run(path: Path) -> EvalRun:
    return EvalRun.from_dict(json.loads(path.read_text(encoding="utf-8")))


def format_summary(run: EvalRun) -> str:
    low, high = wilson_ci(run.exact_match_count, run.n)
    lines = [
        f"{run.exact_match_count}/{run.n} exact ({run.exact_match_rate:.0%}, 95% CI "
        f"{low:.0%}-{high:.0%}), {run.error_count} errors, {run.avg_seconds:.1f}s/call avg"
    ]
    if run.leaked_files:
        clean_n = len(run.clean_results)
        lines.append(
            f"{len(run.leaked_files)} example(s) share a value with the few-shot examples; "
            f"excluding them: {run.clean_exact_match_count}/{clean_n} exact"
        )
    accuracy = run.per_position_accuracy()
    if accuracy:
        lines.append("per-position accuracy: " + " ".join(f"{a:.0%}" for a in accuracy))
    confusions = run.confusions()
    if confusions:
        top = ", ".join(
            f"{e}->{p} x{count}" for (e, p), count in confusions.most_common(5)
        )
        lines.append(f"top digit confusions: {top}")
    return "\n".join(lines)


def compare_runs(baseline: EvalRun, candidate: EvalRun) -> str:
    """Human-readable diff between two eval runs against the same example set.

    Named per-file regressions/improvements matter more than the headline
    rate: a prompt change that trades one failure for a different one at the
    same overall accuracy is invisible in the rate alone but is exactly the
    kind of thing worth knowing before shipping it.
    """
    def headline(tag: str, run: EvalRun) -> str:
        low, high = wilson_ci(run.exact_match_count, run.n)
        return (
            f"{tag} {run.label} ({run.model}) - "
            f"{run.exact_match_count}/{run.n} exact "
            f"({run.exact_match_rate:.0%}, CI {low:.0%}-{high:.0%}), {run.error_count} errors, "
            f"{run.avg_seconds:.1f}s/call avg"
        )

    lines = [headline("Baseline: ", baseline), headline("Candidate:", candidate), ""]

    baseline_by_file = {r.file: r for r in baseline.results}
    candidate_by_file = {r.file: r for r in candidate.results}
    common_files = sorted(set(baseline_by_file) & set(candidate_by_file))

    regressions = [
        f for f in common_files if baseline_by_file[f].exact_match and not candidate_by_file[f].exact_match
    ]
    improvements = [
        f for f in common_files if not baseline_by_file[f].exact_match and candidate_by_file[f].exact_match
    ]

    if regressions:
        lines.append(f"REGRESSIONS ({len(regressions)}) - correct in baseline, wrong in candidate:")
        for f in regressions:
            lines.append(
                f"  {f}: expected {baseline_by_file[f].expected!r}, "
                f"candidate got {candidate_by_file[f].predicted!r}"
            )
    else:
        lines.append("No regressions.")

    if improvements:
        lines.append(f"IMPROVEMENTS ({len(improvements)}) - wrong in baseline, correct in candidate:")
        for f in improvements:
            lines.append(f"  {f}: baseline got {baseline_by_file[f].predicted!r}, now correct")

    p_value = mcnemar_p(len(regressions), len(improvements))
    verdict = "significant" if p_value < 0.05 else "not significant"
    lines.append(
        f"\nPaired McNemar exact test on {len(common_files)} common files: "
        f"p = {p_value:.3f} ({verdict} at 0.05)"
    )
    delta = candidate.avg_seconds - baseline.avg_seconds
    lines.append(f"Latency delta: {delta:+.1f}s/call avg")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Water meter VLM OCR evaluation harness.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a model against an example split.")
    run_parser.add_argument("--host", required=True, help="Ollama host:port")
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--label", required=True, help="Short name for this run, e.g. 'qwen3-vl-8b'")
    run_parser.add_argument("--timeout", type=float, default=480.0)
    run_parser.add_argument("--dynamic-examples-dir", type=Path, default=None)
    run_parser.add_argument("--golden-dir", type=Path, default=GOLDEN_SET_DIR)
    run_parser.add_argument("--results-dir", type=Path, default=EVAL_RESULTS_DIR)
    run_parser.add_argument(
        "--split", choices=(*SPLITS, "all"), default="verify",
        help="verify (default, for tuning) or test/all (sealed - needs --final)",
    )
    run_parser.add_argument("--final", action="store_true", help="Allow running the sealed test split.")
    run_parser.add_argument("--repeat", type=int, default=1, help="Run N times and report determinism.")
    run_parser.add_argument(
        "--strict-leakage", action="store_true",
        help="Refuse to run if an eval value also appears in the few-shot examples.",
    )
    run_parser.add_argument("--no-provenance", action="store_true")

    compare_parser = subparsers.add_parser("compare", help="Diff two saved eval runs.")
    compare_parser.add_argument("baseline", type=Path)
    compare_parser.add_argument("candidate", type=Path)

    list_parser = subparsers.add_parser("list", help="List saved eval runs.")
    list_parser.add_argument("--results-dir", type=Path, default=EVAL_RESULTS_DIR)

    args = parser.parse_args()

    if args.command == "run":
        runs = []
        for attempt in range(1, args.repeat + 1):
            label = args.label if args.repeat == 1 else f"{args.label}-r{attempt}"
            try:
                run = run_eval(
                    host=args.host,
                    model=args.model,
                    label=label,
                    golden_dir=args.golden_dir,
                    timeout=args.timeout,
                    dynamic_examples_dir=args.dynamic_examples_dir,
                    split=args.split,
                    final=args.final,
                    strict_leakage=args.strict_leakage,
                    collect_provenance_info=not args.no_provenance,
                )
            except EvalError as exc:
                raise SystemExit(f"error: {exc}") from exc
            path = save_eval_run(run, args.results_dir)
            print("\n" + format_summary(run))
            print(f"Saved to {path}")
            runs.append(run)
        if len(runs) > 1:
            first = [r.predicted for r in runs[0].results]
            same = all([r.predicted for r in other.results] == first for other in runs[1:])
            print(f"\nDeterministic across {len(runs)} runs: {'yes' if same else 'NO'}")
    elif args.command == "compare":
        baseline = load_eval_run(args.baseline)
        candidate = load_eval_run(args.candidate)
        print(compare_runs(baseline, candidate))
    elif args.command == "list":
        results_dir = args.results_dir
        if not results_dir.exists():
            print("No eval results yet.")
            return
        for path in sorted(results_dir.glob("*.json")):
            run = load_eval_run(path)
            print(
                f"{path.name}: {run.label} ({run.model}, {run.split}) - "
                f"{run.exact_match_count}/{run.n} exact ({run.exact_match_rate:.0%}), "
                f"{run.avg_seconds:.1f}s/call avg"
            )


if __name__ == "__main__":
    main()
