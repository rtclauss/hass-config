from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "allium_weed_check.py"
SPEC = importlib.util.spec_from_file_location("allium_weed_check", SCRIPT_PATH)
assert SPEC is not None
weed = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = weed
SPEC.loader.exec_module(weed)


def test_parse_json_stream_accepts_allium_multi_object_output() -> None:
    payloads = weed.parse_json_stream('{"spec_file":"a.allium","diagnostics":[]}\n{"spec_file":"b.allium","diagnostics":[]}')

    assert [payload["spec_file"] for payload in payloads] == ["a.allium", "b.allium"]


def test_fallback_structural_check_fails_double_equals(tmp_path: Path) -> None:
    spec = tmp_path / "bad.allium"
    spec.write_text(
        "\n".join(
            [
                "-- allium: 3",
                "entity Example {",
                "    enabled: Boolean",
                "}",
                "rule BadEquality {",
                "    when: ExampleChanged()",
                "    requires: example.enabled == true",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    diagnostics = weed.fallback_structural_check([spec])

    assert any(diagnostic.code == "allium.syntax.doubleEquals" for diagnostic in diagnostics)
    assert any(diagnostic.is_error for diagnostic in diagnostics)


def test_require_allium_fails_when_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weed.shutil, "which", lambda _: None)

    diagnostics, notes = weed.run_allium_check([], require_allium=True)

    assert notes == []
    assert diagnostics[0].code == "allium.execution.missingCli"
    assert diagnostics[0].is_error


def test_protected_implementation_change_without_spec_change_fails() -> None:
    scope = weed.ProtectedScope(
        spec="specs/night_routines.allium",
        description="night behavior",
        implementation_paths=("packages/tv.yaml",),
    )

    findings = weed.detect_drift_risks(["packages/tv.yaml"], [scope], [])

    assert len(findings) == 1
    assert findings[0].is_failure
    assert findings[0].changed_implementation == ("packages/tv.yaml",)


def test_protected_implementation_change_with_spec_change_is_covered() -> None:
    scope = weed.ProtectedScope(
        spec="specs/night_routines.allium",
        description="night behavior",
        implementation_paths=("packages/tv.yaml",),
    )

    findings = weed.detect_drift_risks(
        ["packages/tv.yaml", "specs/night_routines.allium"],
        [scope],
        [],
    )

    assert len(findings) == 1
    assert not findings[0].is_failure
    assert findings[0].changed_spec


def test_classified_gap_allows_protected_implementation_change() -> None:
    scope = weed.ProtectedScope(
        spec="specs/z2m_lifecycle.allium",
        description="z2m behavior",
        implementation_paths=("packages/z2m_lifecycle.yaml",),
    )
    classified_gaps = [
        {
            "spec": "specs/z2m_lifecycle.allium",
            "implementation_paths": ["packages/z2m_lifecycle.yaml"],
            "classification": "intentional gap",
            "reason": "Tracked separately with exact issue links.",
        }
    ]

    findings = weed.detect_drift_risks(["packages/z2m_lifecycle.yaml"], [scope], classified_gaps)

    assert len(findings) == 1
    assert not findings[0].is_failure
    assert findings[0].classification == "intentional gap"


def test_classified_gap_can_be_limited_to_changed_line_patterns() -> None:
    scope = weed.ProtectedScope(
        spec="specs/alarm_wakeup.allium",
        description="wake-up behavior",
        implementation_paths=("packages/media_player.yaml",),
    )
    classified_gaps = [
        {
            "spec": "specs/alarm_wakeup.allium",
            "implementation_paths": ["packages/media_player.yaml"],
            "allowed_changed_line_patterns": ['-*"spotify:*', '+*"spotify:*'],
            "classification": "media-uri-pool change",
            "reason": "Exact media URIs are outside the spec.",
        }
    ]

    findings = weed.detect_drift_risks(
        ["packages/media_player.yaml"],
        [scope],
        classified_gaps,
        {"packages/media_player.yaml": ['-"spotify:album:abc",']},
    )

    assert len(findings) == 1
    assert not findings[0].is_failure
    assert findings[0].classification == "media-uri-pool change"


def test_classified_gap_rejects_non_matching_changed_lines() -> None:
    scope = weed.ProtectedScope(
        spec="specs/alarm_wakeup.allium",
        description="wake-up behavior",
        implementation_paths=("packages/media_player.yaml",),
    )
    classified_gaps = [
        {
            "spec": "specs/alarm_wakeup.allium",
            "implementation_paths": ["packages/media_player.yaml"],
            "allowed_changed_line_patterns": ['-*"spotify:*', '+*"spotify:*'],
            "classification": "media-uri-pool change",
            "reason": "Exact media URIs are outside the spec.",
        }
    ]

    findings = weed.detect_drift_risks(
        ["packages/media_player.yaml"],
        [scope],
        classified_gaps,
        {"packages/media_player.yaml": ["-delay:", "+delay:"]},
    )

    assert len(findings) == 1
    assert findings[0].is_failure
    assert findings[0].classification is None


def test_default_config_lists_existing_specs_and_scopes() -> None:
    scopes, classified_gaps = weed.load_config(weed.DEFAULT_CONFIG)

    assert classified_gaps == [
        {
            "spec": "specs/alarm_wakeup.allium",
            "implementation_paths": ["packages/media_player.yaml"],
            "allowed_changed_line_patterns": ['-*"spotify:*', '+*"spotify:*'],
            "classification": "media-uri-pool change",
            "reason": (
                "Exact media URIs and playlist composition are explicitly excluded by "
                "specs/alarm_wakeup.allium; PR #800 only removes Panic-related Spotify "
                "selections from randomized media pools without changing wake-up "
                "scheduling, playback verification, retry, fallback, or volume-ramp "
                "behavior."
            ),
        },
        {
            "spec": "specs/alarm_wakeup.allium",
            "implementation_paths": ["packages/workday.yaml"],
            "allowed_changed_line_patterns": [
                '-*radio_uri: "library://radio/12"',
                '+*radio_uri: "library://radio/21"',
            ],
            "classification": "media-library-record repair",
            "reason": (
                "Exact media URIs are explicitly excluded by specs/alarm_wakeup.allium; "
                "issue #875 and PR #876 replace KSDJ's stale Music Assistant library "
                "record without changing wake-up scheduling, playback verification, "
                "retry, fallback, grouping, or volume-ramp behavior."
            ),
        },
        {
            "spec": "specs/alarm_wakeup.allium",
            "implementation_paths": ["packages/media_player.yaml"],
            "classification": "non-wakeup-scope change",
            "reason": (
                "Issue #801 hardens bedtime playback fallback in script.spotify_bedtime "
                "and centralizes LoFi playlist selection; wake-up scheduling, playback "
                "verification, retry, fallback, and volume-ramp behavior governed by "
                "alarm_wakeup.allium are unchanged."
            ),
        },
        {
            "spec": "specs/night_routines.allium",
            "implementation_paths": ["packages/media_player.yaml"],
            "classification": "non-night-scope change",
            "reason": (
                "Issue #772 hardens wake-up radio playback verification, retry, "
                "and fallback in script.music_assistant_radio_wake_up; bedtime and "
                "goodnight behavior governed by night_routines.allium is unchanged."
            ),
        },
        {
            "spec": "specs/arrival_lighting.allium",
            "implementation_paths": ["packages/adaptive_lighting.yaml"],
            "classification": "arrival-lighting implementation detail",
            "reason": (
                "PR #843 preserves the arrival_lighting.allium empty-house and "
                "manual-control gates while moving Adaptive Lighting turn-on execution "
                "into script.adaptive_light_turn_on so color temperature is corrected "
                "immediately and brightness ramps over the requested transition."
            ),
        }
    ]
    assert {scope.spec for scope in scopes} == {
        "specs/alarm_wakeup.allium",
        "specs/arrival_lighting.allium",
        "specs/night_routines.allium",
        "specs/tv_watching.allium",
        "specs/z2m_lifecycle.allium",
    }
    assert all(scope.implementation_paths for scope in scopes)


def test_markdown_report_includes_line_links(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "rtclauss/hass-config")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    diagnostic = weed.Diagnostic(
        severity="error",
        code="allium.syntax.doubleEquals",
        message="bad equality",
        file="specs/alarm_wakeup.allium",
        line=12,
    )

    report = weed.render_markdown(
        [Path("specs/alarm_wakeup.allium")],
        [diagnostic],
        [],
        [],
    )

    assert "https://github.com/rtclauss/hass-config/blob/abc123/specs/alarm_wakeup.allium#L12" in report
    assert "`allium.syntax.doubleEquals`" in report


def test_markdown_report_requires_owner_approval_before_spec_update() -> None:
    finding = weed.DriftFinding(
        scope=weed.ProtectedScope(
            spec="specs/night_routines.allium",
            description="night behavior",
            implementation_paths=("packages/tv.yaml",),
        ),
        changed_implementation=("packages/tv.yaml",),
        changed_spec=False,
    )

    report = weed.render_markdown(
        [Path("specs/night_routines.allium")],
        [],
        [finding],
        [],
    )

    assert "compare behavior to the governing Allium spec" in report
    assert "only update the spec with owner approval" in report
    assert "otherwise add a classified gap" in report


def test_terminal_report_requires_owner_approval_before_spec_update() -> None:
    finding = weed.DriftFinding(
        scope=weed.ProtectedScope(
            spec="specs/night_routines.allium",
            description="night behavior",
            implementation_paths=("packages/tv.yaml",),
        ),
        changed_implementation=("packages/tv.yaml",),
        changed_spec=False,
    )

    report = weed.render_terminal(
        [Path("specs/night_routines.allium")],
        [],
        [finding],
        [],
    )

    assert "compare behavior to the governing Allium spec" in report
    assert "only update the spec with owner approval" in report
    assert "otherwise add a classified gap" in report


def test_config_json_is_valid() -> None:
    data = json.loads(weed.DEFAULT_CONFIG.read_text(encoding="utf-8"))

    assert isinstance(data["protected_scopes"], list)


def test_sync_github_issues_creates_issue_for_failing_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = tmp_path / "specs" / "bad.allium"
    spec.parent.mkdir()
    spec.write_text("-- allium: 3\n", encoding="utf-8")
    diagnostic = weed.Diagnostic(
        severity="error",
        code="allium.syntax.doubleEquals",
        message="bad equality",
        file="specs/bad.allium",
        line=5,
    )
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, path: str, token: str, payload=None):
        calls.append((method, path))
        if method == "GET":
            return []
        return {"number": 1}

    monkeypatch.setattr(weed, "_github_api", fake_api)

    weed.sync_github_issues([spec], [diagnostic], "owner/repo", "tok")

    methods = [c[0] for c in calls]
    assert "POST" in methods
    post_path = next(p for m, p in calls if m == "POST" and "issues" in p and "labels" not in p)
    assert post_path == "/repos/owner/repo/issues"


def test_sync_github_issues_updates_existing_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = tmp_path / "specs" / "bad.allium"
    spec.parent.mkdir()
    spec.write_text("-- allium: 3\n", encoding="utf-8")
    diagnostic = weed.Diagnostic(
        severity="error",
        code="allium.syntax.doubleEquals",
        message="bad equality",
        file="specs/bad.allium",
    )
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, path: str, token: str, payload=None):
        calls.append((method, path))
        if method == "GET":
            return [{"number": 42, "title": "Allium weed: specs/bad.allium"}]
        return {}

    monkeypatch.setattr(weed, "_github_api", fake_api)

    weed.sync_github_issues([spec], [diagnostic], "owner/repo", "tok")

    assert ("PATCH", "/repos/owner/repo/issues/42") in calls
    assert not any(m == "POST" and "issues" in p and "labels" not in p for m, p in calls)


def test_sync_github_issues_closes_resolved_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = tmp_path / "specs" / "good.allium"
    spec.parent.mkdir()
    spec.write_text("-- allium: 3\n", encoding="utf-8")
    monkeypatch.setattr(weed, "ROOT", tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, path: str, token: str, payload=None):
        calls.append((method, path))
        if method == "GET":
            return [{"number": 7, "title": "Allium weed: specs/good.allium"}]
        return {}

    monkeypatch.setattr(weed, "_github_api", fake_api)

    weed.sync_github_issues([spec], [], "owner/repo", "tok")

    assert ("PATCH", "/repos/owner/repo/issues/7") in calls
