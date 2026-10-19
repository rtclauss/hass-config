from __future__ import annotations

from pathlib import Path


def test_pre_commit_skips_worktrees_before_appdaemon_sync() -> None:
    hook_path = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert 'if [ ! -d "$repo_root/.git" ]; then' in hook_text
    assert "Worktrees are often pinned to older" in hook_text
