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
import ast
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
PROMOTABLE_BUDGET = 30000
MAX_CHANGE_LINES_PER_GROUP = 12
MAX_FILES_PER_GROUP = 40
MAX_EXCLUSION_LINES = 25
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
INCOMPLETE_REASON = "vendored snapshot is incomplete in git (imports or platforms missing; see .gitignore allow-list)"
DELETED = "deleted"


def _state(repo: Path, ref: str, path: str) -> str:
    """Tree-entry state of a path at a ref: file mode and blob id (or DELETED), so mode-only changes count."""
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", ref, "--", path], capture_output=True, text=True
    )
    fields = result.stdout.split("\t", 1)[0].split()
    return f"{fields[0]}:{fields[2]}" if result.returncode == 0 and len(fields) == 3 else DELETED


def _is_ancestor(repo: Path, commit: str, other: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, other], capture_output=True
    ).returncode == 0


def _head_states(repo: Path, head: str, path: str) -> list[tuple[str, str]]:
    """(commit, state) for each first-parent commit on head that changed path, oldest first."""
    raw = git(
        repo, "log", "--first-parent", "--diff-merges=first-parent", "--reverse", "--format=%H",
        "--raw", "--no-abbrev", "--no-renames", head, "--", path,
    )
    entries: list[tuple[str, str]] = []
    commit = ""
    for line in raw.splitlines():
        if re.fullmatch(r"[0-9a-f]{40}", line):
            commit = line
        elif line.startswith(":"):
            fields = line.split()
            entries.append((commit, DELETED if fields[1] == "000000" else f"{fields[1]}:{fields[3]}"))
    return entries


def diverged_files(repo: Path, base: str, head: str, paths: set[str]) -> set[str]:
    """Files whose history on base is not a pure fast-forward through head's history.

    Walks every first-parent commit on base since the merge base that touched the
    path (including ones whose net effect is zero, such as promote-then-revert) and
    requires each resulting state (file mode and blob) to be a later state from
    head's first-parent history than the previous one. The walk starts at the state
    head had at the merge base. A file promoted and edited again on head passes; a
    hotfix, a revert, a mode change or a deletion on base does not.
    """
    merge_base = git(repo, "merge-base", base, head).strip()
    touched_on_base: set[str] = set()
    for line in git(
        repo, "log", "--first-parent", "--diff-merges=first-parent", "--no-renames",
        "--name-only", "--format=", f"{merge_base}..{base}",
    ).splitlines():
        if line.strip() in paths:
            touched_on_base.add(line.strip())
    diverged: set[str] = set()
    for path in sorted(touched_on_base):
        entries = _head_states(repo, head, path)
        positions: dict[str, list[int]] = collections.defaultdict(list)
        for index, (_, state) in enumerate(entries):
            positions[state].append(index)
        # Anchor at the last head commit that is already part of the merge base.
        current = -1
        for index in range(len(entries) - 1, -1, -1):
            if _is_ancestor(repo, entries[index][0], merge_base):
                current = index
                break
        commits = git(
            repo, "log", "--first-parent", "--reverse", "--format=%H", f"{merge_base}..{base}", "--", path
        ).split()
        for sha in commits:
            state = _state(repo, sha, path)
            later = [q for q in positions.get(state, []) if q >= current]
            if not later:
                diverged.add(path)
                break
            current = min(later)
    return diverged


def _top_level_names(source: str, include_imports: bool = False) -> set[str]:
    """Names a module defines at top level (def/class/assignment/PEP 695 alias, optionally imports)."""
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return names
    type_alias = getattr(ast, "TypeAlias", None)  # Python 3.12+
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif type_alias is not None and isinstance(node, type_alias) and isinstance(node.name, ast.Name):
            names.add(node.name.id)
        elif include_imports and isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def incomplete_vendored_units(repo: Path, head: str, units: set[str]) -> set[str]:
    """Vendored integrations whose tracked snapshot cannot import itself.

    The repo's .gitignore is an allow-list, so brand-new files from a HACS update are
    silently left out while edited ones are committed. Promoting such a snapshot
    would put an integration on main that imports files git does not have. Python
    sources are parsed with ast, so multi-line imports and comments are handled.
    """
    wanted = {u for u in units if u.startswith(VENDORED_PREFIX)}
    if not wanted:
        return set()
    tree = set(git(repo, "ls-tree", "-r", "--name-only", head, "custom_components").splitlines())

    def source(path: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"{head}:{path}"], capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else ""

    def module_exists(target: str) -> bool:
        return f"{target}.py" in tree or f"{target}/__init__.py" in tree

    names_cache: dict[tuple[str, bool], set[str]] = {}

    def module_names(path: str, include_imports: bool, depth: int = 0) -> set[str]:
        """Top-level names of a tracked module, following `from .x import *` up to three levels."""
        key = (path, include_imports)
        if key in names_cache:
            return names_cache[key]
        text = source(path)
        names = _top_level_names(text, include_imports)
        names_cache[key] = names  # also guards against import cycles
        if include_imports and depth < 3:
            try:
                body = ast.parse(text).body
            except (SyntaxError, ValueError):
                body = []
            for node in body:
                if isinstance(node, ast.ImportFrom) and node.level and node.module and any(a.name == "*" for a in node.names):
                    folder = path.rsplit("/", 1)[0]
                    for _ in range(node.level - 1):
                        folder = folder.rsplit("/", 1)[0]
                    target = f"{folder}/{node.module.replace('.', '/')}"
                    for candidate in (f"{target}.py", f"{target}/__init__.py"):
                        if candidate in tree:
                            names |= module_names(candidate, True, depth + 1)
                            break
        return names

    def package_defines(folder: str, name: str, include_imports: bool = False) -> bool:
        return name in module_names(f"{folder}/__init__.py", include_imports)

    bad: set[str] = set()
    for path in sorted(tree):
        unit = unit_of(path)
        if not path.endswith(".py") or unit not in wanted or unit in bad:
            continue
        try:
            module = ast.parse(source(path))
        except (SyntaxError, ValueError):
            continue
        folder = path.rsplit("/", 1)[0]
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.level:
                base = folder
                for _ in range(node.level - 1):
                    base = base.rsplit("/", 1)[0]
                if node.module:
                    target = f"{base}/{node.module.replace('.', '/')}"
                    if not module_exists(target):
                        bad.add(unit)
                    elif f"{target}/__init__.py" in tree:
                        # `from .pkg import child`: each name is a submodule or something the package exports.
                        for alias in node.names:
                            if (
                                alias.name != "*"
                                and not module_exists(f"{target}/{alias.name}")
                                and not package_defines(target, alias.name, include_imports=True)
                            ):
                                bad.add(unit)
                else:
                    # Inside the package's own __init__.py an import cannot define the name it imports,
                    # so be strict there; other modules may use anything the package re-exports.
                    strict = path == f"{base}/__init__.py"
                    for alias in node.names:
                        if (
                            alias.name != "*"
                            and not module_exists(f"{base}/{alias.name}")
                            and not package_defines(base, alias.name, include_imports=not strict)
                        ):
                            bad.add(unit)
            elif (
                path.count("/") == 2  # custom_components/<name>/<module>.py, where PLATFORMS lists live
                and isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "Platform"
                and not module_exists(f"{unit}/{node.attr.lower()}")
            ):
                bad.add(unit)
            if unit in bad:
                break
    return bad


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
    if days < 1:
        raise ValueError("days must be at least 1")
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

    # Paths that differ but that head has not touched since the fork were changed on base
    # only (a deletion, hotfix or revert there); promoting around them would break atomic units.
    for path in status:
        if path not in age:
            excluded.setdefault(path, DIVERGED_REASON)
            age[path] = 0.0
    for path in sorted(diverged_files(repo, base, head, set(age))):
        excluded.setdefault(path, DIVERGED_REASON)
        age[path] = 0.0

    for unit in sorted(incomplete_vendored_units(repo, head, {unit_of(p) for p in age})):
        for path in status:
            if path in age and unit_of(path) == unit:
                excluded.setdefault(path, INCOMPLETE_REASON)
                age[path] = 0.0

    # Holds are tracked as a set, not just as age 0, so no threshold can make them promotable.
    held = set(excluded)

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
        if quiet >= days and not any(f in held for u in members for f in unit_files[u]):
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
        elif any(age[p] < days or p in held for p in remaining):
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
    if budget <= 0 or not changes:
        return f"- … {len(changes)} change(s) not listed (run the script locally for the full list)" if changes else "- none"
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


def _cluster_block(
    cluster: Cluster, audit: Audit, by_file: dict[str, list[Change]], repo: Path | None
) -> list[str]:
    title = ", ".join(f"`{u}`" for u in cluster.units[:3])
    if len(cluster.units) > 3:
        title += f" +{len(cluster.units) - 3} more"
    block = [
        f"### {title}"[:300],
        f"Quiet for **{int(cluster.quiet_days)} days** · {len(cluster.files)} file(s)",
        "",
    ]
    seen: dict[str, Change] = {}
    for path in cluster.files:
        for change in by_file.get(path, []):
            seen[change.sha] = change
    ordered = sorted(seen.values(), key=lambda ch: ch.ts)
    block += [_change_line(change, audit)[:300] for change in ordered[:MAX_CHANGE_LINES_PER_GROUP]]
    if len(ordered) > MAX_CHANGE_LINES_PER_GROUP:
        block.append(f"- … {len(ordered) - MAX_CHANGE_LINES_PER_GROUP} more change(s)")
    if repo is not None:
        for unit in (u for u in cluster.units if u.startswith(VENDORED_PREFIX)):
            before = _vendored_version(repo, audit.base, unit)
            after = _vendored_version(repo, audit.head, unit)
            if after and before != after:
                block.append(f"- `{unit}` version {before or 'none'} → {after}")
    block += ["", "<details><summary>Files</summary>", ""]
    block += [f"- `{audit.status[f]}` {f}"[:300] for f in cluster.files[:MAX_FILES_PER_GROUP]]
    if len(cluster.files) > MAX_FILES_PER_GROUP:
        block.append(f"- … {len(cluster.files) - MAX_FILES_PER_GROUP} more")
    block += ["", "</details>", ""]
    return block


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
        used = 0
        for position, cluster in enumerate(audit.promotable):
            block = _cluster_block(cluster, audit, by_file, repo)
            size = sum(len(line) + 1 for line in block)
            if used + size > PROMOTABLE_BUDGET:
                out += [
                    f"- … {len(audit.promotable) - position} more group(s) omitted to fit GitHub's size limit. "
                    "The full list is in the `promotion-audit-files` artifact or from running the script locally.",
                    "",
                ]
                break
            out += block
            used += size

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
            f"{len(audit.excluded)} file(s) are held back: listed in `docs/promotion_audit_exclusions.yaml`, also changed on `main`, or part of a vendored snapshot that is incomplete in git:",
            "",
        ]
        reasons = collections.defaultdict(list)
        for path, reason in sorted(audit.excluded.items()):
            reasons[reason].append(path)
        for reason, paths in list(reasons.items())[:MAX_EXCLUSION_LINES]:
            line = f"- {reason}: " + ", ".join(f"`{p}`" for p in paths[:6]) + (f" +{len(paths) - 6} more" if len(paths) > 6 else "")
            out.append(line[:500])
        if len(reasons) > MAX_EXCLUSION_LINES:
            out.append(f"- … {len(reasons) - MAX_EXCLUSION_LINES} more reason(s)")
        out.append("")

    head_text = "\n".join(out)
    budget = MAX_BODY_CHARS - len(head_text) - 1200  # room for the ledger wrappers
    held = c["entangled"] + c["partial"]
    soaking = c["soaking"]
    total = len(held) + len(soaking) or 1
    held_budget = max(budget * len(held) // total, 0)
    soak_budget = max(budget - held_budget, 0)
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
    text = head_text + "\n" + "\n".join(tail) + "\n"
    if len(text) > MAX_BODY_CHARS:  # last-resort guard; the budgets above should prevent this
        text = text[: MAX_BODY_CHARS - 100].rsplit("\n", 1)[0] + "\n\n_(report truncated)_\n"
    return text


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", type=Path)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="origin/develop")
    parser.add_argument("--days", type=_positive_int, default=DEFAULT_DAYS)
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
