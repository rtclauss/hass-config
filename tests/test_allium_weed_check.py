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


def test_default_config_lists_existing_specs_and_scopes() -> None:
    scopes, classified_gaps = weed.load_config(weed.DEFAULT_CONFIG)

    assert classified_gaps == []
    assert {scope.spec for scope in scopes} == {
        "specs/alarm_wakeup.allium",
        "specs/night_routines.allium",
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


def test_config_json_is_valid() -> None:
    data = json.loads(weed.DEFAULT_CONFIG.read_text(encoding="utf-8"))

    assert isinstance(data["protected_scopes"], list)
