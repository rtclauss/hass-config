from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "validate-config.yml"


def test_esphome_build_only_runs_for_changed_esphome_yaml() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "detect-esphome-changes:" in workflow_text
    assert "grep -E '^esphome/.*\\.ya?ml$'" in workflow_text
    assert 'if [[ "$config" =~ ^esphome/[^/]+\\.ya?ml$ ]]; then' in workflow_text
    assert 'grep -l "^packages:" esphome/*.yaml' in workflow_text
    assert "esphome_changed: ${{ steps.detect.outputs.esphome_changed }}" in workflow_text
    assert "esphome_configs: ${{ steps.detect.outputs.esphome_configs }}" in workflow_text
    assert "if: ${{ needs.detect-esphome-changes.outputs.esphome_changed == 'true' }}" in workflow_text
    assert "ESPHOME_CONFIGS: ${{ needs.detect-esphome-changes.outputs.esphome_configs }}" in workflow_text
    assert "while IFS= read -r config; do" in workflow_text


def test_home_assistant_config_check_does_not_depend_on_esphome_build() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    ha_section = workflow_text.split("home-assistant-check-config:", maxsplit=1)[1]
    ha_needs_section = ha_section.split("    steps:", maxsplit=1)[0]

    assert "    needs: yaml-lint" in ha_needs_section
    assert "esphome-build" not in ha_needs_section


def test_home_assistant_config_check_pins_known_good_image() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "HOME_ASSISTANT_CHECK_CONFIG_IMAGE: ghcr.io/home-assistant/home-assistant:2026.3.4" in workflow_text
    assert "home-assistant/core#167066" in workflow_text
    assert '"$HOME_ASSISTANT_CHECK_CONFIG_IMAGE" \\' in workflow_text


def test_yaml_lint_covers_esphome_directory() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "          esphome \\" in workflow_text
