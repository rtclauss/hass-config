from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "promotion_audit.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "promotion-audit.yml"

spec = importlib.util.spec_from_file_location("promotion_audit", SCRIPT)
promotion_audit = importlib.util.module_from_spec(spec)
sys.modules["promotion_audit"] = promotion_audit
spec.loader.exec_module(promotion_audit)

NOW = 1_800_000_000
DAY = 86400


def git(repo: Path, *args: str, when: int | None = None) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(repo),
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{when} +0000"
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    ).stdout


def commit(repo: Path, files: dict[str, str], days_ago: float, message: str) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, when=int(NOW - days_ago * DAY))


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(
        tmp_path,
        {
            "README.md": "base\n",
            "packages/base.yaml": "a: 1\n",
            "custom_components/foo/manifest.json": '{"version": "0.9.0"}\n',
            "custom_components/foo/x.py": "x = 0\n",
        },
        200,
        "base",
    )
    git(tmp_path, "checkout", "-q", "-b", "develop")

    # A: two files changed together, 60d ago; README (meta) must not link it to C.
    commit(tmp_path, {"packages/a1.yaml": "1\n", "packages/a2.yaml": "1\n", "README.md": "a\n"}, 60, "Add A (#1)")
    # B shares a hub with C, which is recent: B is old but entangled.
    commit(tmp_path, {"packages/b.yaml": "1\n", "packages/hub.yaml": "1\n"}, 50, "Add B (#2)")
    commit(tmp_path, {"packages/hub.yaml": "2\n", "README.md": "c\n"}, 2, "Tweak hub (#3)")
    # X is old and touches no recent file itself, but shares b.yaml with B: entangled.
    commit(tmp_path, {"packages/x1.yaml": "1\n", "packages/b.yaml": "2\n"}, 55, "Add X (#9)")
    # Vendored integration bump, quiet.
    commit(
        tmp_path,
        {"custom_components/foo/manifest.json": '{"version": "1.0.0"}\n', "custom_components/foo/x.py": "x = 1\n"},
        40,
        "update foo (#4)",
    )
    # Vendored integration touched recently: soaking.
    commit(tmp_path, {"custom_components/bar/y.py": "y = 1\n"}, 3, "add bar (#8)")
    # Excluded by the exclusions list even though old.
    commit(tmp_path, {"packages/excl.yaml": "1\n"}, 45, "Add excluded (#5)")
    # Wide sweep: ignored for linking, so each file stands alone.
    commit(tmp_path, {f"packages/w{i}.yaml": "1\n" for i in range(25)}, 45, "Sweep (#6)")
    # PR merged with a merge commit.
    git(tmp_path, "checkout", "-q", "-b", "feat")
    commit(tmp_path, {"packages/h1.yaml": "1\n"}, 36, "wip h1")
    commit(tmp_path, {"packages/h2.yaml": "1\n"}, 35, "wip h2")
    git(tmp_path, "checkout", "-q", "develop")
    git(
        tmp_path,
        "merge",
        "--no-ff",
        "-q",
        "-m",
        "Merge pull request #7 from owner/feat",
        "-m",
        "Add H feature",
        "feat",
        when=int(NOW - 35 * DAY),
    )
    return tmp_path


def audit(repo: Path, **kwargs):
    return promotion_audit.run_audit(repo, base="main", head="develop", now=NOW, **kwargs)


def test_promotable_files_are_isolated_and_quiet(repo: Path) -> None:
    result = audit(repo, exclusions=[("packages/excl.yaml", "held on purpose")])
    files = set(result.promotable_files)

    assert {"packages/a1.yaml", "packages/a2.yaml"} <= files
    assert {"packages/h1.yaml", "packages/h2.yaml"} <= files
    assert {f"packages/w{i}.yaml" for i in range(25)} <= files
    assert {"custom_components/foo/manifest.json", "custom_components/foo/x.py"} <= files
    # Entangled with a recent change, recent itself, or excluded.
    assert "packages/b.yaml" not in files
    assert "packages/hub.yaml" not in files
    assert "custom_components/bar/y.py" not in files
    assert "packages/excl.yaml" not in files
    # Meta files are never promoted on their own.
    assert "README.md" not in files


def test_meta_files_do_not_link_changes(repo: Path) -> None:
    result = audit(repo)
    # README.md was touched by both A (60d) and C (2d); A must stay promotable.
    assert "packages/a1.yaml" in result.promotable_files


def test_change_states(repo: Path) -> None:
    result = audit(repo, exclusions=[("packages/excl.yaml", "held")])
    states = {
        name: {c.label for c in changes} for name, changes in result.changes.items()
    }

    assert "#1" in states["promotable"]
    assert "#4" in states["promotable"]
    assert "#6" in states["promotable"]
    assert "#2" in states["soaking"]  # touches the recently changed hub itself
    assert "#9" in states["entangled"]  # old, but tied to the hub through b.yaml
    assert "#3" in states["soaking"]
    assert "#8" in states["soaking"]
    assert "#5" in states["soaking"]  # excluded files count as recently changed


def test_merge_commit_pr_number_and_title(repo: Path) -> None:
    result = audit(repo)
    merged = [c for c in result.all_changes if c.pr == 7]

    assert len(merged) == 1
    assert merged[0].title == "Add H feature"
    assert merged[0].files == {"packages/h1.yaml", "packages/h2.yaml"}


def test_blockers_point_at_recent_hub(repo: Path) -> None:
    result = audit(repo)

    assert ("packages/hub.yaml", pytest.approx(2.0), 1) in result.blockers


def test_larger_threshold_holds_more_back(repo: Path) -> None:
    result = audit(repo, days=55)
    files = set(result.promotable_files)

    assert "packages/a1.yaml" in files  # 60d
    assert "packages/h1.yaml" not in files  # 35d
    assert "custom_components/foo/x.py" not in files  # 40d


def test_exclusions_file_parsing(tmp_path: Path) -> None:
    path = tmp_path / "ex.txt"
    path.write_text("# comment\n\n- \"custom_components/places/**\"  # v3\n- packages/x.yaml\n", encoding="utf-8")

    assert promotion_audit.load_exclusions(path) == [
        ("custom_components/places/*", "v3"),
        ("packages/x.yaml", ""),
    ]
    assert promotion_audit.load_exclusions(tmp_path / "missing.txt") == []


def test_markdown_report_and_files_out(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    out_dir = tmp_path_factory.mktemp("out")
    report_path = out_dir / "report.md"
    files_path = out_dir / "files.txt"
    exclusions = out_dir / "ex.txt"
    exclusions.write_text("packages/excl.yaml  # held on purpose\n", encoding="utf-8")

    rc = promotion_audit.main(
        [
            "--repo", str(repo),
            "--base", "main",
            "--head", "develop",
            "--exclusions", str(exclusions),
            "--now", str(NOW),
            "--output", str(report_path),
            "--files-out", str(files_path),
        ]
    )

    report = report_path.read_text(encoding="utf-8")
    assert rc == 0
    assert report.startswith("<!-- promotion-audit -->")
    assert "## Promotable now" in report
    assert "`custom_components/foo` version 0.9.0 → 1.0.0" in report
    assert "## What is blocking the rest" in report
    assert "packages/hub.yaml" in report
    assert "held on purpose" in report
    assert len(report) < promotion_audit.MAX_BODY_CHARS
    lines = files_path.read_text(encoding="utf-8").splitlines()
    assert "A\tpackages/a1.yaml" in lines
    assert "M\tcustom_components/foo/x.py" in lines


def test_ledger_respects_budget() -> None:
    changes = [
        promotion_audit.Change(f"{i:040x}", NOW - i, "x" * 80, i, frozenset({"f"})) for i in range(500)
    ]
    ledger = promotion_audit._ledger(changes, None, 1000)

    assert len(ledger) < 1300
    assert "more (run the script locally" in ledger


def test_workflow_runs_weekly_and_only_writes_issues() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in text and "cron:" in text
    assert "workflow_dispatch:" in text
    assert "contents: read" in text
    assert "issues: write" in text
    assert "pull-requests: write" not in text
    assert "fetch-depth: 0" in text
    assert "python scripts/promotion_audit.py" in text
    assert "promotion-audit" in text
    assert "gh issue edit" in text and "gh issue create" in text
