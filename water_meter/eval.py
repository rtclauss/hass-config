"""Regression/comparison harness for the VLM OCR tier.

Every round of model/prompt comparison in this project so far (see the
"Reading Through Glare" report) was a one-off ad hoc script, run once,
discarded, and reconstructed from scratch next time - including a real
resolution A/B test in this same session that had to be redesigned twice
after a methodology mistake, purely because there was no reusable harness
enforcing a consistent, already-solved approach. This module fixes that: a
versioned golden set (water_meter/golden_set/, visually-verified real
captures spanning ~3 days) plus a runner that scores any model/prompt/
dynamic-examples combination against it the same way every time, and a
diff tool to compare two runs directly.

Saved results (eval_results/*.json) are meant to be committed to git - the
whole point is a durable, greppable history of "what did we try and what
happened", not a scratch file that gets overwritten. `python3 -m
water_meter.eval run` to add one, `compare` to diff two.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from . import ocr

GOLDEN_SET_DIR = Path(__file__).parent / "golden_set"
EVAL_RESULTS_DIR = Path(__file__).parent / "eval_results"


@dataclass(frozen=True)
class GoldenExample:
    file: str
    digits: str
    capture_width: int = 0
    capture_height: int = 0


def load_golden_set(golden_dir: Path = GOLDEN_SET_DIR) -> list[GoldenExample]:
    manifest = json.loads((golden_dir / "manifest.json").read_text(encoding="utf-8"))
    return [
        GoldenExample(
            file=entry["file"],
            digits=entry["digits"],
            capture_width=int(entry.get("capture_width", 0)),
            capture_height=int(entry.get("capture_height", 0)),
        )
        for entry in manifest
    ]


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

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "model": self.model,
            "host": self.host,
            "timestamp": self.timestamp,
            "dynamic_examples_dir": self.dynamic_examples_dir,
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


def run_eval(
    *,
    host: str,
    model: str,
    label: str,
    golden_dir: Path = GOLDEN_SET_DIR,
    timeout: float = 480.0,
    dynamic_examples_dir: Path | None = None,
    progress: bool = True,
) -> EvalRun:
    """Run one model/config against the whole golden set.

    Deliberately calls ocr.read_digits_vlm directly (not ocr.read_digits) -
    this harness measures the VLM tier itself, not the full ssocr-first
    fallback chain, since ssocr essentially never succeeds on this meter
    (0/16 in the report's own three-way comparison) and would just add
    constant, uninteresting overhead to every run.
    """
    examples = load_golden_set(golden_dir)
    run = EvalRun(
        label=label,
        model=model,
        host=host,
        timestamp=datetime.now(timezone.utc).isoformat(),
        dynamic_examples_dir=str(dynamic_examples_dir) if dynamic_examples_dir else None,
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
            print(
                f"[{i}/{len(examples)}] {example.file}: {predicted!r} "
                f"(expected {example.digits!r}) {mark} {elapsed:.1f}s",
                flush=True,
            )
    return run


def save_eval_run(run: EvalRun, results_dir: Path = EVAL_RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = run.timestamp.replace(":", "").replace("-", "").split(".")[0]
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in run.label)
    path = results_dir / f"{stamp}_{safe_label}.json"
    path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
    return path


def load_eval_run(path: Path) -> EvalRun:
    return EvalRun.from_dict(json.loads(path.read_text(encoding="utf-8")))


def compare_runs(baseline: EvalRun, candidate: EvalRun) -> str:
    """Human-readable diff between two eval runs against the same golden set.

    Named per-file regressions/improvements matter more than the headline
    rate: a prompt change that trades one failure for a different one at the
    same overall accuracy is invisible in the rate alone but is exactly the
    kind of thing worth knowing before shipping it.
    """
    lines = [
        f"Baseline:  {baseline.label} ({baseline.model}) - "
        f"{baseline.exact_match_count}/{baseline.n} exact "
        f"({baseline.exact_match_rate:.0%}), {baseline.error_count} errors, "
        f"{baseline.avg_seconds:.1f}s/call avg",
        f"Candidate: {candidate.label} ({candidate.model}) - "
        f"{candidate.exact_match_count}/{candidate.n} exact "
        f"({candidate.exact_match_rate:.0%}), {candidate.error_count} errors, "
        f"{candidate.avg_seconds:.1f}s/call avg",
        "",
    ]

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

    delta = candidate.avg_seconds - baseline.avg_seconds
    lines.append(f"\nLatency delta: {delta:+.1f}s/call avg")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Water meter VLM OCR evaluation harness.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a model against the golden set.")
    run_parser.add_argument("--host", required=True, help="Ollama host:port")
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--label", required=True, help="Short name for this run, e.g. 'qwen3-vl-8b'")
    run_parser.add_argument("--timeout", type=float, default=480.0)
    run_parser.add_argument("--dynamic-examples-dir", type=Path, default=None)
    run_parser.add_argument("--golden-dir", type=Path, default=GOLDEN_SET_DIR)
    run_parser.add_argument("--results-dir", type=Path, default=EVAL_RESULTS_DIR)

    compare_parser = subparsers.add_parser("compare", help="Diff two saved eval runs.")
    compare_parser.add_argument("baseline", type=Path)
    compare_parser.add_argument("candidate", type=Path)

    list_parser = subparsers.add_parser("list", help="List saved eval runs.")
    list_parser.add_argument("--results-dir", type=Path, default=EVAL_RESULTS_DIR)

    args = parser.parse_args()

    if args.command == "run":
        run = run_eval(
            host=args.host,
            model=args.model,
            label=args.label,
            golden_dir=args.golden_dir,
            timeout=args.timeout,
            dynamic_examples_dir=args.dynamic_examples_dir,
        )
        path = save_eval_run(run, args.results_dir)
        print(
            f"\n{run.exact_match_count}/{run.n} exact ({run.exact_match_rate:.0%}), "
            f"{run.error_count} errors, {run.avg_seconds:.1f}s/call avg"
        )
        print(f"Saved to {path}")
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
                f"{path.name}: {run.label} ({run.model}) - "
                f"{run.exact_match_count}/{run.n} exact ({run.exact_match_rate:.0%}), "
                f"{run.avg_seconds:.1f}s/call avg"
            )


if __name__ == "__main__":
    main()
