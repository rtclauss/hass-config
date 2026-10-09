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
    # A vendored snapshot that imports a file git does not have, and a complete one.
    commit(tmp_path, {"custom_components/inc/__init__.py": "from .frontend import register\n"}, 41, "add inc (#12)")
    commit(
        tmp_path,
        {
            "custom_components/okc/__init__.py": "from .helper import x\nPLATFORMS = [Platform.SENSOR]\n",
            "custom_components/okc/helper.py": "x = 1\n",
            "custom_components/okc/sensor.py": "y = 1\n",
        },
        41,
        "add okc (#13)",
    )
    # An isolated file edited twice on develop (45d, 40d).
    commit(tmp_path, {"packages/base.yaml": "a: 2\n"}, 45, "Edit base (#10)")
    commit(tmp_path, {"packages/base.yaml": "a: 3\n"}, 40, "Edit base again (#11)")
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


def test_already_promoted_files_drop_out_of_the_delta(repo: Path) -> None:
    # Promote A by copying it onto a branch of main (no merge, no shared ancestry).
    git(repo, "checkout", "-q", "-b", "main_copied", "main")
    git(repo, "checkout", "develop", "--", "packages/a1.yaml", "packages/a2.yaml")
    git(repo, "commit", "-q", "-m", "copy A", when=NOW - DAY)
    git(repo, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(repo, base="main_copied", head="develop", now=NOW)

    assert "packages/a1.yaml" not in result.status
    assert "packages/a1.yaml" not in result.promotable_files
    assert "packages/a2.yaml" not in result.promotable_files
    assert "packages/h1.yaml" in result.promotable_files  # still outstanding


def test_older_develop_version_on_main_is_a_fast_forward(repo: Path) -> None:
    # main holds the 45d version of base.yaml; develop has since edited it again (40d).
    first = git(repo, "log", "--format=%H", "--grep=Edit base (#10)", "develop").strip()
    git(repo, "checkout", "-q", "-b", "main_ff", "main")
    git(repo, "checkout", first, "--", "packages/base.yaml")
    git(repo, "commit", "-q", "-m", "promote base v1", when=NOW - DAY)
    git(repo, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(repo, base="main_ff", head="develop", now=NOW)

    assert "packages/base.yaml" in result.status
    assert "packages/base.yaml" not in result.excluded
    assert "packages/base.yaml" in result.promotable_files


def test_independent_change_on_main_holds_the_file_back(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "main_hotfix", "main")
    commit(repo, {"packages/base.yaml": "a: hotfix\n"}, 1, "hotfix on main")
    git(repo, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(repo, base="main_hotfix", head="develop", now=NOW)

    assert result.excluded["packages/base.yaml"] == promotion_audit.DIVERGED_REASON
    assert "packages/base.yaml" not in result.promotable_files
    # Unrelated files are unaffected.
    assert "packages/a1.yaml" in result.promotable_files
    assert "Held back on purpose" in promotion_audit.render_markdown(result, repo)


def test_revert_on_main_after_promotion_holds_the_file_back(repo: Path) -> None:
    # main promoted base.yaml (develop's 45d version), then reverted it to the pre-fork
    # content. The final tree matches the merge base, but the history shows a deliberate revert.
    first = git(repo, "log", "--format=%H", "--grep=Edit base (#10)", "develop").strip()
    git(repo, "checkout", "-q", "-b", "main_reverted", "main")
    git(repo, "checkout", first, "--", "packages/base.yaml")
    git(repo, "commit", "-q", "-m", "promote base", when=NOW - 20 * DAY)
    commit(repo, {"packages/base.yaml": "a: 1\n"}, 10, "revert base")
    git(repo, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(repo, base="main_reverted", head="develop", now=NOW)

    assert result.excluded["packages/base.yaml"] == promotion_audit.DIVERGED_REASON
    assert "packages/base.yaml" not in result.promotable_files


def test_incomplete_vendored_snapshot_is_held_back(repo: Path) -> None:
    result = audit(repo)

    assert "custom_components/inc/__init__.py" not in result.promotable_files
    assert result.excluded["custom_components/inc/__init__.py"] == promotion_audit.INCOMPLETE_REASON
    assert "custom_components/okc/__init__.py" in result.promotable_files
    assert "custom_components/foo/x.py" in result.promotable_files


def test_side_branch_blob_is_not_a_valid_promoted_version(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"packages/f.yaml": "a: base\n"}, 200, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    git(tmp_path, "checkout", "-q", "-b", "feat")
    commit(tmp_path, {"packages/f.yaml": "a: X\n"}, 70, "feature edit (#1)")  # only ever on the side branch
    git(tmp_path, "checkout", "-q", "develop")
    commit(tmp_path, {"packages/f.yaml": "a: Z\n"}, 65, "develop edit (#2)")
    # Conflict resolution produces Y, which matches neither parent, so a plain
    # `git log -- path` also walks the side branch and sees X.
    git(tmp_path, "merge", "--no-ff", "--no-commit", "-s", "ours", "-q", "feat")
    (tmp_path / "packages" / "f.yaml").write_text("a: Y\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "Merge pull request #3 from o/feat", when=NOW - 60 * DAY)
    # main independently hotfixes the file to exactly X.
    git(tmp_path, "checkout", "-q", "-b", "main_hotfix", "main")
    commit(tmp_path, {"packages/f.yaml": "a: X\n"}, 20, "hotfix on main")
    git(tmp_path, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(tmp_path, base="main_hotfix", head="develop", now=NOW)

    assert result.excluded["packages/f.yaml"] == promotion_audit.DIVERGED_REASON
    assert "packages/f.yaml" not in result.promotable_files


def test_report_stays_within_the_issue_size_limit_for_huge_sweeps(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"README.md": "base\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    # A wide sweep of 700 files is ignored for linking, so each file is its own group.
    commit(tmp_path, {f"packages/very_long_package_name_number_{i:04d}.yaml": "1\n" for i in range(700)}, 60, "Sweep (#1)")
    for i in range(30):
        commit(tmp_path, {f"packages/soak_{i}.yaml": "1\n"}, 2, f"Recent change {i} (#{10 + i})")

    result = promotion_audit.run_audit(tmp_path, base="main", head="develop", now=NOW)
    report = promotion_audit.render_markdown(result, tmp_path)

    assert len(result.promotable) >= 700
    assert len(report) <= promotion_audit.MAX_BODY_CHARS
    assert "more group(s) omitted to fit GitHub's size limit" in report
    assert "## Promotable now" in report
    assert report.count("<details>") == report.count("</details>")


def test_threshold_below_one_day_is_rejected(repo: Path) -> None:
    with pytest.raises(ValueError):
        promotion_audit.run_audit(repo, base="main", head="develop", days=0, now=NOW)
    with pytest.raises(SystemExit):
        promotion_audit.parse_args(["--days", "0"])


def test_holds_do_not_depend_on_the_age_threshold(repo: Path) -> None:
    result = audit(repo, days=1, exclusions=[("packages/excl.yaml", "held")])

    assert "packages/excl.yaml" not in result.promotable_files
    assert "custom_components/inc/__init__.py" not in result.promotable_files  # incomplete snapshot


def test_platform_list_in_const_module_is_checked(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"README.md": "base\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(
        tmp_path,
        {
            "custom_components/bm/__init__.py": "from .const import PLATFORMS\n",
            "custom_components/bm/const.py": "PLATFORMS = [Platform.SENSOR, Platform.BUTTON]\n",
            "custom_components/bm/sensor.py": "x = 1\n",
        },
        60,
        "add bm (#1)",
    )  # button.py was silently ignored by the allow-list

    result = promotion_audit.run_audit(tmp_path, base="main", head="develop", now=NOW)

    assert "custom_components/bm/const.py" not in result.promotable_files
    assert result.excluded["custom_components/bm/const.py"] == promotion_audit.INCOMPLETE_REASON


def test_version_revisited_on_develop_is_not_divergence(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"packages/f.yaml": "a: A\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(tmp_path, {"packages/f.yaml": "a: B\n"}, 80, "edit to B (#1)")
    commit(tmp_path, {"packages/f.yaml": "a: A\n"}, 60, "revert to A (#2)")  # develop revisits A
    # main already promoted B (a valid develop state).
    git(tmp_path, "checkout", "-q", "-b", "main_b", "main")
    commit(tmp_path, {"packages/f.yaml": "a: B\n"}, 70, "promote B")
    git(tmp_path, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(tmp_path, base="main_b", head="develop", now=NOW)

    assert "packages/f.yaml" not in result.excluded
    assert "packages/f.yaml" in result.promotable_files


def test_main_only_deletion_holds_the_whole_vendored_unit(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(
        tmp_path,
        {"custom_components/foo/__init__.py": "from .y import z\n", "custom_components/foo/y.py": "z = 1\n"},
        300,
        "base",
    )
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(tmp_path, {"custom_components/foo/__init__.py": "from .y import z\nx = 2\n"}, 60, "update foo (#1)")
    git(tmp_path, "checkout", "-q", "-b", "main_del", "main")
    git(tmp_path, "rm", "-q", "custom_components/foo/y.py")
    git(tmp_path, "commit", "-q", "-m", "drop y on main", when=NOW - 10 * DAY)
    git(tmp_path, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(tmp_path, base="main_del", head="develop", now=NOW)

    assert "custom_components/foo/__init__.py" not in result.promotable_files
    assert result.excluded["custom_components/foo/y.py"] == promotion_audit.DIVERGED_REASON


def test_rollback_is_caught_when_the_merge_base_state_occurred_earlier(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"packages/f.yaml": "a: B\n"}, 300, "B")
    commit(tmp_path, {"packages/f.yaml": "a: A\n"}, 290, "A")
    commit(tmp_path, {"packages/f.yaml": "a: B\n"}, 280, "B again")  # merge base state
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(tmp_path, {"packages/f.yaml": "a: C\n"}, 60, "C (#1)")
    git(tmp_path, "checkout", "-q", "-b", "main_rollback", "main")
    commit(tmp_path, {"packages/f.yaml": "a: A\n"}, 30, "deliberate rollback on main")
    git(tmp_path, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(tmp_path, base="main_rollback", head="develop", now=NOW)

    assert result.excluded["packages/f.yaml"] == promotion_audit.DIVERGED_REASON
    assert "packages/f.yaml" not in result.promotable_files


def test_mode_only_change_on_main_counts_as_divergence(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"scripts/run.sh": "echo 1\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(tmp_path, {"scripts/run.sh": "echo 2\n"}, 60, "edit script (#1)")
    git(tmp_path, "checkout", "-q", "-b", "main_exec", "main")
    (tmp_path / "scripts" / "run.sh").chmod(0o755)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "make executable", when=NOW - 20 * DAY)
    git(tmp_path, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(tmp_path, base="main_exec", head="develop", now=NOW)

    assert result.excluded["scripts/run.sh"] == promotion_audit.DIVERGED_REASON


def test_module_less_relative_imports_are_checked(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"README.md": "base\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(tmp_path, {"custom_components/zz/__init__.py": "from . import frontend\n"}, 60, "add zz (#1)")
    commit(
        tmp_path,
        {
            "custom_components/yy/__init__.py": "DOMAIN = 'yy'\nfrom . import helpers\n",
            "custom_components/yy/helpers.py": "x = 1\n",
            "custom_components/yy/sensor.py": "from . import DOMAIN\n",
        },
        60,
        "add yy (#2)",
    )

    result = promotion_audit.run_audit(tmp_path, base="main", head="develop", now=NOW)

    assert result.excluded["custom_components/zz/__init__.py"] == promotion_audit.INCOMPLETE_REASON
    assert "custom_components/yy/__init__.py" in result.promotable_files
    assert "custom_components/yy/sensor.py" in result.promotable_files


def test_multiline_imports_and_commented_platforms(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"README.md": "base\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    commit(
        tmp_path,
        {"custom_components/ml/__init__.py": "from . import (\n    helpers,\n    frontend,\n)\n", "custom_components/ml/helpers.py": "x = 1\n"},
        60,
        "add ml (#1)",
    )  # frontend.py was ignored by the allow-list
    commit(
        tmp_path,
        {
            "custom_components/cm/__init__.py": "from .const import PLATFORMS\n",
            "custom_components/cm/const.py": "PLATFORMS = [\n    Platform.SENSOR,\n    # Platform.BUTTON,\n]\n",
            "custom_components/cm/sensor.py": "x = 1\n",
        },
        60,
        "add cm (#2)",
    )

    result = promotion_audit.run_audit(tmp_path, base="main", head="develop", now=NOW)

    assert result.excluded["custom_components/ml/__init__.py"] == promotion_audit.INCOMPLETE_REASON
    assert "custom_components/cm/const.py" in result.promotable_files  # commented-out platform is ignored


def test_main_following_a_deletion_and_readd_on_develop_is_not_divergence(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"packages/f.yaml": "a: 1\n"}, 300, "base")
    git(tmp_path, "checkout", "-q", "-b", "develop")
    git(tmp_path, "rm", "-q", "packages/f.yaml")
    git(tmp_path, "commit", "-q", "-m", "drop f (#1)", when=NOW - 70 * DAY)
    commit(tmp_path, {"packages/f.yaml": "a: 2\n"}, 50, "re-add f (#2)")
    # main already promoted develop's deletion.
    git(tmp_path, "checkout", "-q", "-b", "main_deleted", "main")
    git(tmp_path, "rm", "-q", "packages/f.yaml")
    git(tmp_path, "commit", "-q", "-m", "promote deletion", when=NOW - 60 * DAY)
    git(tmp_path, "checkout", "-q", "develop")

    result = promotion_audit.run_audit(tmp_path, base="main_deleted", head="develop", now=NOW)

    assert "packages/f.yaml" not in result.excluded
    assert "packages/f.yaml" in result.promotable_files


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
    assert "must come from `develop`" in report
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
