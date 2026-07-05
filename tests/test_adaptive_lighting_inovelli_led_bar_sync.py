from __future__ import annotations

from pathlib import Path


ADAPTIVE_LIGHTING_PATH = (
    Path(__file__).resolve().parents[1] / "packages" / "adaptive_lighting.yaml"
)


def _automation_block(automation_id: str) -> str:
    lines = ADAPTIVE_LIGHTING_PATH.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if line not in (f"    id: {automation_id}", f"  - id: {automation_id}"):
            continue

        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_adaptive_lighting_no_longer_syncs_inovelli_led_bars() -> None:
    contents = ADAPTIVE_LIGHTING_PATH.read_text(encoding="utf-8")

    assert "sync_selected_inovelli_led_bars_to_adaptive_lighting" not in contents
    assert "sync_inovelli_led_bars_to_adaptive_lighting" not in contents
    assert "owner suite and office Inovelli LED bars" not in contents
    assert "number.owner_suite_fan_switch_ledcolorwhenon" not in contents
    assert "number.office_fan_switch_ledcolorwhenon" not in contents


def test_nightly_adaptive_lighting_cycle_filters_missing_candidate_switches() -> None:
    block = _automation_block("nightly_adaptive_lighting_cycle_reset")

    assert "candidate_main_adaptive_switches:" in block
    assert "switch.adaptive_lighting_office" not in block
    assert "states(entity_id) not in ['unknown', 'unavailable']" in block
    assert "main_adaptive_switches | count > 0" in block
    assert block.count('entity_id: "{{ main_adaptive_switches }}"') == 2


def test_arrival_spec_no_longer_requires_inovelli_led_bar_sync() -> None:
    spec_path = ADAPTIVE_LIGHTING_PATH.parents[1] / "specs" / "arrival_lighting.allium"
    contents = spec_path.read_text(encoding="utf-8")

    assert "SyncSelectedInovelliLedBarsToAdaptiveLighting" not in contents
    assert "AdaptiveLightingTargetChanged" not in contents
    assert "SelectedInovelliLedBarsMirrorAdaptiveLighting" not in contents
