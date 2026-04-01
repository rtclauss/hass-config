from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GITIGNORE_PATH = ROOT / ".gitignore"
SKILL_PATH = ROOT / ".codex" / "skills" / "trace-review" / "SKILL.md"
REFERENCE_PATH = ROOT / ".codex" / "skills" / "trace-review" / "references" / "sweep-playbook.md"
AGENT_PATH = ROOT / ".codex" / "skills" / "trace-review" / "agents" / "openai.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_gitignore_tracks_trace_review_skill_files() -> None:
    text = _read(GITIGNORE_PATH)

    assert "!.codex/" in text
    assert "!.codex/skills/" in text
    assert "!.codex/skills/trace-review/" in text
    assert "!.codex/skills/trace-review/**" in text


def test_trace_review_skill_defines_issue_and_sweep_modes() -> None:
    text = _read(SKILL_PATH)

    assert "## Modes" in text
    assert "`Issue mode`" in text
    assert "`Sweep mode`" in text
    assert "references/sweep-playbook.md" in text


def test_trace_review_skill_anchors_live_trace_tools_and_repo_guardrails() -> None:
    text = _read(SKILL_PATH)

    assert "ha_get_overview(detail_level=\"minimal\", include_entity_id=True)" in text
    assert "ha_search_entities(query=\"\", domain_filter=\"automation\")" in text
    assert "ha_get_automation_traces(<entity_id>, limit=10)" in text
    assert "docs/room_intent.yaml" in text
    assert "uv run --with pytest pytest" in text


def test_trace_review_reference_covers_issue_and_pr_triage() -> None:
    text = _read(REFERENCE_PATH)

    assert "## GitHub Triage Loop" in text
    assert "look for an existing open issue first" in text
    assert "check whether an open PR already references it" in text
    assert "branch from `origin/develop`" in text


def test_trace_review_agent_prompt_mentions_skill_and_pr_ready_updates() -> None:
    text = _read(AGENT_PATH)

    assert 'display_name: "Trace Review"' in text
    assert 'default_prompt: "Use $trace-review' in text
    assert "PR-ready issue update" in text
    assert "allow_implicit_invocation: true" in text
