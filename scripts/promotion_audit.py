#!/usr/bin/env python3
"""Report which develop work is quiet enough to promote to main.

Rule: a file is promotable only if everything it was ever changed together with
(same first-parent change on develop) has also been quiet for N days. That keeps
main from receiving half of a feature. custom_components are judged per
integration and never linked to other files; README/AGENTS/.gitignore/CI churn
is ignored when linking changes. Files matching the exclusions file count as
recently changed, so they hold back everything tied to them.

Uses git only (no network). See docs/promotion_audit.md.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import fnmatch
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_DAYS = 30
DEFAULT_WIDE = 20
MAX_BODY_CHARS = 60000
META_FILES = {"README.md", "AGENTS.md", ".gitignore", "inventory.md"}
META_PREFIXES = (".github/",)
VENDORED_PREFIX = "custom_components/"
PR_SUFFIX = re.compile(r"\(#(\d+)\)\s*$")
PR_MERGE = re.compile(r"^Merge pull request #(\d+)\b")
DAY = 86400.0


@dataclasses.dataclass(frozen=True)
class Change:
    """One first-parent change on develop: a squash commit, PR merge, or direct commit."""

    sha: str
    ts: int
    title: str
    pr: int | None
    files: frozenset[str]

    @property
    def label(self) -> str:
        return f"#{self.pr}" if self.pr else self.sha[:7]


@dataclasses.dataclass
class Cluster:
    units: list[str]
    files: list[str]
    quiet_days: float


@dataclasses.dataclass
class Audit:
    base: str
    head: str
    base_sha: str
    head_sha: str
    days: int
    now: float
    status: dict[str, str]
    age: dict[str, float]
    promotable: list[Cluster]
    changes: dict[str, list[Change]]  # state -> changes
    blockers: list[tuple[str, float, int]]
    excluded: dict[str, str]  # file -> reason
    promotable_files: list[str]
    all_changes: list[Change] = dataclasses.field(default_factory=list)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def is_meta(path: str) -> bool:
    return path in META_FILES or path.startswith(META_PREFIXES)


def unit_of(path: str) -> str:
    if path.startswith(VENDORED_PREFIX):
        parts = path.split("/")
        if len(parts) > 2:
            return "/".join(parts[:2])
    return path


def load_exclusions(path: Path | None) -> list[tuple[str, str]]:
    if path is None or not path.is_file():
        return []
    rules: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line, _, reason = raw.partition("#")
        pattern = line.strip()
        if pattern.startswith("- "):
            pattern = pattern[2:].strip()
        pattern = pattern.strip("\"'")
        if pattern:
            rules.append((pattern.replace("**", "*"), reason.strip()))
    return rules


def load_changes(repo: Path, base: str, head: str) -> list[Change]:
    out = git(
        repo,
        "log",
        "--first-parent",
        "--diff-merges=first-parent",
        "--no-renames",
        "--name-only",
        f"--format=%x1e%H%x1f%ct%x1f%s%x1f%b%x1f",
        f"{base}..{head}",
    )
    changes: list[Change] = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        sha, ts, subject, body, tail = record.split("\x1f", 4)
        files = frozenset(line for line in tail.splitlines() if line.strip())
        pr: int | None = None
        title = subject.strip()
        merged = PR_MERGE.match(subject)
        if merged:
            pr = int(merged.group(1))
            first_body_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
            title = first_body_line or title
        else:
            suffix = PR_SUFFIX.search(subject)
            if suffix:
                pr = int(suffix.group(1))
        changes.append(Change(sha.strip(), int(ts), title, pr, files))
    return changes


def load_status(repo: Path, base: str, head: str) -> dict[str, str]:
    """Outstanding delta between the two branch trees (not against their merge base).

    A three-dot diff would keep reporting files that were already promoted by
    copying them (or by a squash merge), because their commits are not ancestors.
    """
    out = git(repo, "diff", "--name-status", "--no-renames", base, head)
    status: dict[str, str] = {}
    for line in out.splitlines():
        code, _, path = line.partition("\t")
        if path:
            status[path] = code[0]
    return status


DIVERGED_REASON = "also changed on main since the branches diverged"


def _blob(repo: Path, ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def diverged_files(repo: Path, base: str, head: str, paths: set[str]) -> set[str]:
    """Files whose base version is not simply an older version from head's history.

    A file promoted earlier and edited again on head is a fast-forward and fine.
    A file edited independently on base (a revert, a hotfix) would be overwritten.
    """
    merge_base = git(repo, "merge-base", base, head).strip()
    changed_on_base = (
        set(git(repo, "diff", "--name-only", "--no-renames", merge_base, base).splitlines()) & paths
    )
    diverged: set[str] = set()
    for path in sorted(changed_on_base):
        base_blob = _blob(repo, base, path)
        raw = git(repo, "log", "--format=", "--raw", "--no-abbrev", "--no-renames", head, "--", path)
        history = {line.split()[3] for line in raw.splitlines() if line.startswith(":")}
        if base_blob is None or base_blob not in history:
            diverged.add(path)
    return diverged


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def run_audit(
    repo: Path,
    base: str = "origin/main",
    head: str = "origin/develop",
    days: int = DEFAULT_DAYS,
    wide: int = DEFAULT_WIDE,
    exclusions: list[tuple[str, str]] | None = None,
    now: float | None = None,
) -> Audit:
    now = time.time() if now is None else now
    exclusions = exclusions or []
    status = load_status(repo, base, head)
    changes = load_changes(repo, base, head)

    last: dict[str, int] = {}
    for change in changes:
        for path in change.files:
            if path in status:
                last[path] = max(last.get(path, 0), change.ts)
    age = {path: (now - last[path]) / DAY for path in status if path in last}

    excluded: dict[str, str] = {}
    for path in status:
        for pattern, reason in exclusions:
            if fnmatch.fnmatch(path, pattern):
                excluded[path] = reason or "excluded"
                age[path] = 0.0
                break

    for path in sorted(diverged_files(repo, base, head, set(age))):
        excluded.setdefault(path, DIVERGED_REASON)
        age[path] = 0.0

    unit_age: dict[str, float] = {}
    unit_files: dict[str, list[str]] = collections.defaultdict(list)
    for path in status:
        if path not in age or is_meta(path):
            continue
        unit = unit_of(path)
        unit_files[unit].append(path)
        unit_age[unit] = min(unit_age.get(unit, float("inf")), age[path])

    uf = UnionFind()
    for unit in unit_files:
        uf.find(unit)
    link_edges: list[tuple[Change, list[str]]] = []
    for change in changes:
        units = sorted(
            {
                unit_of(p)
                for p in change.files
                if p in age and not is_meta(p) and not p.startswith(VENDORED_PREFIX)
            }
        )
        if len(change.files) >= wide or len(units) < 1:
            continue
        link_edges.append((change, units))
        for other in units[1:]:
            uf.union(units[0], other)

    groups: dict[str, list[str]] = collections.defaultdict(list)
    for unit in unit_files:
        groups[uf.find(unit)].append(unit)
    clusters: list[Cluster] = []
    promotable_units: set[str] = set()
    for members in groups.values():
        quiet = min(unit_age[u] for u in members)
        if quiet >= days:
            files = sorted(f for u in members for f in unit_files[u])
            clusters.append(Cluster(sorted(members), files, quiet))
            promotable_units.update(members)
    clusters.sort(key=lambda c: (-c.quiet_days, c.units[0]))
    promotable_files = sorted(f for c in clusters for f in c.files)
    promotable_set = set(promotable_files)

    states: dict[str, list[Change]] = {"promotable": [], "partial": [], "entangled": [], "soaking": []}
    for change in changes:
        remaining = [p for p in change.files if p in age and not is_meta(p)]
        if not remaining:
            continue
        in_a = [p for p in remaining if p in promotable_set]
        if len(in_a) == len(remaining):
            states["promotable"].append(change)
        elif any(age[p] < days for p in remaining):
            states["soaking"].append(change)
        elif in_a:
            states["partial"].append(change)
        else:
            states["entangled"].append(change)

    blockers = _blockers(link_edges, unit_age, states, days)
    return Audit(
        base=base,
        head=head,
        base_sha=git(repo, "rev-parse", "--short", base).strip(),
        head_sha=git(repo, "rev-parse", "--short", head).strip(),
        days=days,
        now=now,
        status=status,
        age=age,
        promotable=clusters,
        changes=states,
        blockers=blockers,
        excluded=excluded,
        promotable_files=promotable_files,
        all_changes=changes,
    )


def _blockers(
    link_edges: list[tuple[Change, list[str]]],
    unit_age: dict[str, float],
    states: dict[str, list[Change]],
    days: int,
    limit: int = 12,
) -> list[tuple[str, float, int]]:
    """Nearest recently-changed unit for each quiet-but-held change."""
    unit_changes: dict[str, list[str]] = collections.defaultdict(list)
    change_units: dict[str, list[str]] = {}
    for change, units in link_edges:
        change_units[change.sha] = units
        for unit in units:
            unit_changes[unit].append(change.sha)
    roots = [u for u in unit_changes if unit_age.get(u, float("inf")) < days]
    seen_units: dict[str, str] = {u: u for u in roots}
    seen_changes: dict[str, str] = {}
    queue = collections.deque(roots)
    while queue:
        unit = queue.popleft()
        for sha in unit_changes[unit]:
            if sha in seen_changes:
                continue
            seen_changes[sha] = seen_units[unit]
            for other in change_units[sha]:
                if other not in seen_units:
                    seen_units[other] = seen_units[unit]
                    queue.append(other)
    held = {c.sha for c in states["entangled"] + states["partial"]}
    counts = collections.Counter(root for sha, root in seen_changes.items() if sha in held)
    return [(root, unit_age[root], n) for root, n in counts.most_common(limit)]


def _vendored_version(repo: Path, ref: str, unit: str) -> str | None:
    try:
        text = git(repo, "show", f"{ref}:{unit}/manifest.json")
        return json.loads(text).get("version")
    except (subprocess.CalledProcessError, ValueError):
        return None


def _change_line(change: Change, audit: Audit) -> str:
    day = time.strftime("%Y-%m-%d", time.gmtime(change.ts))
    title = change.title.replace("|", "\\|")
    return f"- {change.label} · {day} · {title}"


def _ledger(changes: list[Change], audit: Audit, budget: int) -> str:
    lines: list[str] = []
    used = 0
    for change in sorted(changes, key=lambda c: c.ts):
        line = _change_line(change, audit)
        if used + len(line) > budget:
            lines.append(f"- … {len(changes) - len(lines)} more (run the script locally for the full list)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def render_markdown(audit: Audit, repo: Path | None = None) -> str:
    stamp = time.strftime("%Y-%m-%d", time.gmtime(audit.now))
    c = audit.changes
    out: list[str] = [
        "<!-- promotion-audit -->",
        f"_Generated {stamp} from `{audit.base}` (`{audit.base_sha}`) → `{audit.head}` (`{audit.head_sha}`); "
        f"threshold {audit.days} days. Updated in place every week by the Promotion Audit workflow._",
        "",
        f"`{audit.head}` is **{len(audit.status)} files** ahead of `{audit.base}`.",
        "",
        "| Bucket | Changes | Meaning |",
        "|---|---|---|",
        f"| Promotable | {len(c['promotable'])} | Fully isolated and quiet for {audit.days}+ days |",
        f"| Quiet but entangled | {len(c['entangled']) + len(c['partial'])} | Old, but share files with code that is still changing |",
        f"| Still soaking | {len(c['soaking'])} | Touch files changed in the last {audit.days} days |",
        "",
        "## Promotable now",
        "",
    ]
    if not audit.promotable:
        out += [f"Nothing is isolated enough yet. See the blockers below.", ""]
    else:
        out += [
            f"{len(audit.promotable_files)} files in {len(audit.promotable)} groups. Treat these as "
            "**candidates** for the next promotion: run `pytest` and the HA config check on the result "
            "before promoting (some tests read shared files such as `README.md`). Promotions into "
            "`main` must come from `develop` (see `AGENTS.md`); anything narrower needs explicit owner approval.",
            "",
        ]
        by_file: dict[str, list[Change]] = {}
        for change in audit.all_changes:
            for path in change.files:
                by_file.setdefault(path, []).append(change)
        for cluster in audit.promotable:
            title = ", ".join(f"`{u}`" for u in cluster.units[:3])
            if len(cluster.units) > 3:
                title += f" +{len(cluster.units) - 3} more"
            out.append(f"### {title}")
            out.append(f"Quiet for **{int(cluster.quiet_days)} days** · {len(cluster.files)} file(s)")
            out.append("")
            seen: dict[str, Change] = {}
            for path in cluster.files:
                for change in by_file.get(path, []):
                    seen[change.sha] = change
            for change in sorted(seen.values(), key=lambda ch: ch.ts):
                out.append(_change_line(change, audit))
            vendored = [u for u in cluster.units if u.startswith(VENDORED_PREFIX)]
            if repo is not None:
                for unit in vendored:
                    before = _vendored_version(repo, audit.base, unit)
                    after = _vendored_version(repo, audit.head, unit)
                    if after and before != after:
                        out.append(f"- `{unit}` version {before or 'none'} → {after}")
            out += ["", "<details><summary>Files</summary>", ""]
            out += [f"- `{audit.status[f]}` {f}" for f in cluster.files[:60]]
            if len(cluster.files) > 60:
                out.append(f"- … {len(cluster.files) - 60} more")
            out += ["", "</details>", ""]

    if audit.blockers:
        out += [
            "## What is blocking the rest",
            "",
            "Recently changed files that tie up the most quiet-but-held changes:",
            "",
            "| File | Last changed | Held changes |",
            "|---|---|---|",
        ]
        out += [f"| `{f}` | {age:.0f}d ago | {n} |" for f, age, n in audit.blockers]
        out.append("")

    if audit.excluded:
        out += [
            "## Held back on purpose",
            "",
            f"{len(audit.excluded)} file(s) are held by `docs/promotion_audit_exclusions.yaml` or because they also changed on `main`:",
            "",
        ]
        reasons = collections.defaultdict(list)
        for path, reason in sorted(audit.excluded.items()):
            reasons[reason].append(path)
        for reason, paths in reasons.items():
            out.append(f"- {reason}: " + ", ".join(f"`{p}`" for p in paths[:6]) + (f" +{len(paths) - 6} more" if len(paths) > 6 else ""))
        out.append("")

    head_text = "\n".join(out)
    budget = MAX_BODY_CHARS - len(head_text) - 600
    held = c["entangled"] + c["partial"]
    soaking = c["soaking"]
    total = len(held) + len(soaking) or 1
    held_budget = max(budget * len(held) // total, 500)
    soak_budget = max(budget - held_budget, 500)
    tail = [
        f"<details><summary>Ledger: {len(held)} quiet-but-entangled changes</summary>",
        "",
        _ledger(held, audit, held_budget),
        "",
        "</details>",
        "",
        f"<details><summary>Ledger: {len(soaking)} changes still soaking</summary>",
        "",
        _ledger(soaking, audit, soak_budget),
        "",
        "</details>",
    ]
    return head_text + "\n" + "\n".join(tail) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", type=Path)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="origin/develop")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--wide", type=int, default=DEFAULT_WIDE, help="ignore changes touching this many files or more when linking")
    parser.add_argument("--exclusions", type=Path, default=Path("docs/promotion_audit_exclusions.yaml"))
    parser.add_argument("--now", type=float, help="treat this epoch time as now (for reproducible runs and tests)")
    parser.add_argument("--output", type=Path, help="write the markdown report here (default: stdout)")
    parser.add_argument("--files-out", type=Path, help="write the promotable files (status<TAB>path) here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    exclusions_path = args.exclusions if args.exclusions.is_absolute() else repo / args.exclusions
    audit = run_audit(
        repo,
        base=args.base,
        head=args.head,
        days=args.days,
        wide=args.wide,
        exclusions=load_exclusions(exclusions_path),
        now=args.now,
    )
    report = render_markdown(audit, repo)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    if args.files_out:
        args.files_out.write_text(
            "".join(f"{audit.status[f]}\t{f}\n" for f in audit.promotable_files), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
