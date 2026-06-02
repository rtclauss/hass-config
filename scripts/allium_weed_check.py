#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "specs" / "allium_weed_config.json"

ERROR_SEVERITIES = {"error", "fatal"}
COLOR = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "cyan": "\033[36m",
    "reset": "\033[0m",
}


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    file: str
    line: int | None = None
    col: int | None = None

    @property
    def is_error(self) -> bool:
        return self.severity.lower() in ERROR_SEVERITIES


@dataclass(frozen=True)
class ProtectedScope:
    spec: str
    description: str
    implementation_paths: tuple[str, ...]


@dataclass(frozen=True)
class DriftFinding:
    scope: ProtectedScope
    changed_implementation: tuple[str, ...]
    changed_spec: bool
    classification: str | None = None
    reason: str | None = None

    @property
    def is_failure(self) -> bool:
        return self.classification is None and not self.changed_spec


def repo_path(path: Path | str) -> str:
    path = Path(path)
    if path.is_absolute():
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def discover_specs(paths: Iterable[str]) -> list[Path]:
    candidates = [ROOT / path for path in paths] if paths else [ROOT / "specs"]
    specs: set[Path] = set()

    for candidate in candidates:
        if candidate.is_file() and candidate.suffix == ".allium":
            specs.add(candidate)
        elif candidate.is_dir():
            specs.update(candidate.rglob("*.allium"))

    return sorted(specs)


def parse_json_stream(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    index = 0
    objects: list[dict[str, Any]] = []

    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        obj, index = decoder.raw_decode(text, index)
        if not isinstance(obj, dict):
            raise ValueError("Allium emitted a non-object JSON payload.")
        objects.append(obj)

    return objects


def _diagnostic_from_payload(item: dict[str, Any], fallback_file: str) -> Diagnostic:
    location = item.get("location") or {}
    return Diagnostic(
        severity=str(item.get("severity") or "error"),
        code=str(item.get("code") or "allium.diagnostic"),
        message=str(item.get("message") or "Allium diagnostic reported."),
        file=str(location.get("file") or fallback_file),
        line=location.get("line"),
        col=location.get("col"),
    )


def run_allium_check(specs: list[Path], require_allium: bool = False) -> tuple[list[Diagnostic], list[str]]:
    allium = shutil.which("allium")
    if allium is None:
        if require_allium:
            return [
                Diagnostic(
                    severity="error",
                    code="allium.execution.missingCli",
                    message="Allium CLI is required for this run but was not found on PATH.",
                    file="specs",
                )
            ], []
        return fallback_structural_check(specs), [
            "Allium CLI was not found; used the repository fallback structural checks. "
            "Install allium for full language validation."
        ]

    command = [allium, "check", *[repo_path(path) for path in specs]]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = result.stdout.strip()
    diagnostics: list[Diagnostic] = []
    notes: list[str] = []

    if not output:
        if result.returncode != 0:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="allium.execution.failed",
                    message=(result.stderr.strip() or "allium check failed without JSON output."),
                    file="specs",
                )
            )
        return diagnostics, notes

    try:
        payloads = parse_json_stream(output)
    except ValueError as exc:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="allium.output.invalidJson",
                message=f"Could not parse allium check JSON output: {exc}",
                file="specs",
            )
        )
        return diagnostics, notes

    for payload in payloads:
        fallback_file = str(payload.get("spec_file") or "specs")
        diagnostics.extend(
            _diagnostic_from_payload(item, fallback_file)
            for item in payload.get("diagnostics", [])
        )
        diagnostics.extend(
            _diagnostic_from_payload(item, fallback_file)
            for item in payload.get("findings", [])
            if isinstance(item, dict)
        )

    if result.stderr.strip():
        notes.append(result.stderr.strip())

    return diagnostics, notes


def fallback_structural_check(specs: list[Path]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for spec in specs:
        relative = repo_path(spec)
        text = spec.read_text(encoding="utf-8")
        lines = text.splitlines()

        if not lines or not lines[0].startswith("-- allium:"):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="allium.header.missingVersion",
                    message="Spec must declare the Allium language version on the first line.",
                    file=relative,
                    line=1,
                )
            )

        for index, line in enumerate(lines, start=1):
            if "==" in line and not line.lstrip().startswith("--"):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="allium.syntax.doubleEquals",
                        message="Allium equality uses '='; '==' is not valid in expressions.",
                        file=relative,
                        line=index,
                    )
                )
            if re.search(r"\bcontext\.", line):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="allium.syntax.unboundContextReference",
                        message="Use the declared given binding instead of an unbound 'context.' reference.",
                        file=relative,
                        line=index,
                    )
                )

        for opener, closer, code in (("{", "}", "braces"), ("(", ")", "parentheses")):
            delta = text.count(opener) - text.count(closer)
            if delta != 0:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code=f"allium.syntax.unbalanced{code.title()}",
                        message=f"Unbalanced {code}: {opener!r} and {closer!r} counts differ.",
                        file=relative,
                    )
                )

    return diagnostics


def load_config(path: Path) -> tuple[list[ProtectedScope], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    scopes = [
        ProtectedScope(
            spec=str(item["spec"]),
            description=str(item.get("description") or ""),
            implementation_paths=tuple(str(path) for path in item.get("implementation_paths", [])),
        )
        for item in data.get("protected_scopes", [])
    ]
    return scopes, list(data.get("classified_gaps", []))


def git_changed_files(changed_from: str) -> list[str]:
    candidates = [
        ["git", "diff", "--name-only", f"{changed_from}...HEAD"],
        ["git", "diff", "--name-only", changed_from, "HEAD"],
    ]
    last_error = ""

    for command in candidates:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0:
            return sorted(line for line in result.stdout.splitlines() if line)
        last_error = result.stderr.strip()

    raise RuntimeError(f"Could not compute changed files from {changed_from!r}: {last_error}")


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _classification_for(scope: ProtectedScope, changed_file: str, classified_gaps: list[dict[str, Any]]) -> dict[str, Any] | None:
    for gap in classified_gaps:
        if gap.get("spec") != scope.spec:
            continue
        files = [str(file) for file in gap.get("implementation_paths", [])]
        if _matches(changed_file, files):
            return gap
    return None


def detect_drift_risks(
    changed_files: Iterable[str],
    scopes: list[ProtectedScope],
    classified_gaps: list[dict[str, Any]],
) -> list[DriftFinding]:
    changed = set(changed_files)
    findings: list[DriftFinding] = []

    for scope in scopes:
        changed_impl = sorted(path for path in changed if _matches(path, scope.implementation_paths))
        if not changed_impl:
            continue

        changed_spec = scope.spec in changed
        unclassified = [
            path for path in changed_impl
            if _classification_for(scope, path, classified_gaps) is None
        ]
        if changed_spec:
            findings.append(DriftFinding(scope, tuple(changed_impl), changed_spec=True))
        elif unclassified:
            findings.append(DriftFinding(scope, tuple(unclassified), changed_spec=False))
        else:
            first_gap = _classification_for(scope, changed_impl[0], classified_gaps)
            findings.append(
                DriftFinding(
                    scope,
                    tuple(changed_impl),
                    changed_spec=False,
                    classification=str(first_gap.get("classification")),
                    reason=str(first_gap.get("reason") or ""),
                )
            )

    return findings


def link_for(path: str, line: int | None = None) -> str:
    sha = os.environ.get("GITHUB_SHA")
    repo = os.environ.get("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

    if sha and repo:
        suffix = f"#L{line}" if line else ""
        return f"{server}/{repo}/blob/{sha}/{path}{suffix}"

    return f"{path}:{line}" if line else path


def _paint(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{COLOR[color]}{text}{COLOR['reset']}"


def render_terminal(
    specs: list[Path],
    diagnostics: list[Diagnostic],
    drift_findings: list[DriftFinding],
    notes: list[str],
) -> str:
    use_color = sys.stdout.isatty()
    failures = [diag for diag in diagnostics if diag.is_error]
    drift_failures = [finding for finding in drift_findings if finding.is_failure]
    lines = [
        _paint("Allium weed check", "cyan", use_color),
        f"Specs checked: {len(specs)}",
    ]

    if failures or drift_failures:
        lines.append(_paint("Status: failed", "red", use_color))
    else:
        lines.append(_paint("Status: passed", "green", use_color))

    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in notes)

    if diagnostics:
        lines.append("")
        lines.append("Allium diagnostics:")
        for diag in diagnostics:
            location = link_for(diag.file, diag.line)
            color = "red" if diag.is_error else "yellow"
            lines.append(f"- {_paint(diag.severity.upper(), color, use_color)} {location} {diag.code}: {diag.message}")

    if drift_findings:
        lines.append("")
        lines.append("Spec/code drift gate:")
        for finding in drift_findings:
            if finding.changed_spec:
                status = _paint("covered", "green", use_color)
                detail = "spec changed in the same diff"
            elif finding.classification:
                status = _paint(f"classified: {finding.classification}", "yellow", use_color)
                detail = finding.reason or "classified gap"
            else:
                status = _paint("unclassified", "red", use_color)
                detail = "update the spec or add a classified gap with a reason"
            lines.append(f"- {status} {finding.scope.spec}: {', '.join(finding.changed_implementation)} ({detail})")

    if not diagnostics and not drift_findings:
        lines.append("")
        lines.append("No Allium diagnostics or protected-scope drift risks found.")

    return "\n".join(lines) + "\n"


def render_markdown(
    specs: list[Path],
    diagnostics: list[Diagnostic],
    drift_findings: list[DriftFinding],
    notes: list[str],
) -> str:
    failures = [diag for diag in diagnostics if diag.is_error]
    drift_failures = [finding for finding in drift_findings if finding.is_failure]
    status = "failed" if failures or drift_failures else "passed"
    lines = [
        "## Allium Weed Check",
        "",
        f"**Status:** {status}",
        f"**Specs checked:** {len(specs)}",
    ]

    if notes:
        lines.extend(["", "### Notes"])
        lines.extend(f"- {note}" for note in notes)

    lines.extend(["", "### Allium Diagnostics"])
    if diagnostics:
        lines.append("| Severity | Location | Code | Message |")
        lines.append("| --- | --- | --- | --- |")
        for diag in diagnostics:
            location = f"[{diag.file}{':' + str(diag.line) if diag.line else ''}]({link_for(diag.file, diag.line)})"
            lines.append(f"| {diag.severity} | {location} | `{diag.code}` | {diag.message} |")
    else:
        lines.append("No structural diagnostics.")

    lines.extend(["", "### Spec/Code Drift Gate"])
    if drift_findings:
        lines.append("| Scope | Changed implementation | Classification | Required next step |")
        lines.append("| --- | --- | --- | --- |")
        for finding in drift_findings:
            files = ", ".join(f"`{path}`" for path in finding.changed_implementation)
            if finding.changed_spec:
                classification = "covered"
                next_step = "Spec changed in the same diff."
            elif finding.classification:
                classification = finding.classification
                next_step = finding.reason or "Review classified gap."
            else:
                classification = "unclassified"
                next_step = "Update the governing `.allium` spec or add a classified gap with a reason and exact links."
            lines.append(f"| `{finding.scope.spec}` | {files} | {classification} | {next_step} |")
    else:
        lines.append("No protected implementation scopes changed.")

    return "\n".join(lines) + "\n"


def _github_api(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_allium_weed_label(repo: str, token: str) -> None:
    try:
        _github_api("POST", f"/repos/{repo}/labels", token, {
            "name": "allium-weed",
            "color": "5319e7",
            "description": "Allium spec validity failure or spec/code drift",
        })
    except urllib.error.HTTPError as exc:
        if exc.code != 422:  # 422 = label already exists
            raise


def _find_open_weed_issue(repo: str, token: str, title: str) -> dict[str, Any] | None:
    issues = _github_api("GET", f"/repos/{repo}/issues?state=open&labels=allium-weed&per_page=100", token)
    return next((i for i in issues if i.get("title") == title), None)


def sync_github_issues(
    specs: list[Path],
    diagnostics: list[Diagnostic],
    repo: str,
    token: str,
) -> None:
    """Create or update one GitHub issue per failing spec; close issues for specs that now pass.

    Only diagnostic errors are tracked — drift findings are ephemeral (PR-specific) and
    are surfaced via the step summary rather than persistent issues.
    """
    _ensure_allium_weed_label(repo, token)

    errors_by_spec: dict[str, list[str]] = {}
    for diag in diagnostics:
        if diag.is_error:
            location = f"[{diag.file}{':' + str(diag.line) if diag.line else ''}]({link_for(diag.file, diag.line)})"
            errors_by_spec.setdefault(diag.file, []).append(
                f"| `{diag.severity}` | {location} | `{diag.code}` | {diag.message} |"
            )

    all_spec_keys = {repo_path(spec) for spec in specs}

    for spec_key, rows in errors_by_spec.items():
        title = f"Allium weed: {spec_key}"
        body = "\n".join([
            f"## Allium weed failures: `{spec_key}`",
            "",
            "### Spec diagnostics",
            "",
            "| Severity | Location | Code | Message |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "_Detected by the Allium weed check. Run `python scripts/allium_weed_check.py "
            "--require-allium --format terminal` locally to reproduce._",
        ])
        existing = _find_open_weed_issue(repo, token, title)
        if existing:
            _github_api("PATCH", f"/repos/{repo}/issues/{existing['number']}", token, {"body": body})
        else:
            _github_api("POST", f"/repos/{repo}/issues", token, {
                "title": title,
                "body": body,
                "labels": ["allium-weed"],
            })

    for spec_key in all_spec_keys - set(errors_by_spec):
        title = f"Allium weed: {spec_key}"
        existing = _find_open_weed_issue(repo, token, title)
        if existing:
            _github_api("PATCH", f"/repos/{repo}/issues/{existing['number']}", token, {
                "state": "closed",
                "state_reason": "completed",
            })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Allium specs and gate protected spec/code drift.")
    parser.add_argument("paths", nargs="*", help="Allium files or directories to validate. Defaults to specs/.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Protected scope config JSON.")
    parser.add_argument("--changed-from", help="Git ref/SHA used to compute changed files for drift gating.")
    parser.add_argument("--format", choices=("terminal", "markdown"), default="terminal")
    parser.add_argument("--output", help="Write the report to this file instead of stdout.")
    parser.add_argument(
        "--require-allium",
        action="store_true",
        help="Fail instead of using fallback structural checks when the allium CLI is missing.",
    )
    parser.add_argument(
        "--create-issues",
        action="store_true",
        help=(
            "Create or update one GitHub issue per spec with diagnostic errors; "
            "close issues for specs that now pass. "
            "Requires GITHUB_TOKEN and GITHUB_REPOSITORY env vars."
        ),
    )
    args = parser.parse_args(argv)

    specs = discover_specs(args.paths)
    if not specs:
        print("No .allium files found.", file=sys.stderr)
        return 2

    diagnostics, notes = run_allium_check(specs, require_allium=args.require_allium)
    scopes, classified_gaps = load_config(Path(args.config))
    drift_findings: list[DriftFinding] = []

    if args.changed_from:
        try:
            changed_files = git_changed_files(args.changed_from)
        except RuntimeError as exc:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="allium.drift.changedFilesUnavailable",
                    message=str(exc),
                    file=".",
                )
            )
        else:
            drift_findings = detect_drift_risks(changed_files, scopes, classified_gaps)

    if args.format == "markdown":
        report = render_markdown(specs, diagnostics, drift_findings, notes)
    else:
        report = render_terminal(specs, diagnostics, drift_findings, notes)

    if args.output:
        output_path = Path(args.output)
        if output_path.exists():
            output_path.write_text(output_path.read_text(encoding="utf-8") + "\n" + report, encoding="utf-8")
        else:
            output_path.write_text(report, encoding="utf-8")
    else:
        print(report, end="")

    if args.create_issues:
        gh_token = os.environ.get("GITHUB_TOKEN")
        gh_repo = os.environ.get("GITHUB_REPOSITORY")
        if gh_token and gh_repo:
            try:
                sync_github_issues(specs, diagnostics, gh_repo, gh_token)
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: failed to sync GitHub issues: {exc}", file=sys.stderr)
        else:
            print(
                "Warning: --create-issues requires GITHUB_TOKEN and GITHUB_REPOSITORY env vars.",
                file=sys.stderr,
            )

    if any(diag.is_error for diag in diagnostics) or any(finding.is_failure for finding in drift_findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
