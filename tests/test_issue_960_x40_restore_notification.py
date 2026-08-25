from __future__ import annotations

from pathlib import Path


VACUUM_PATH = Path(__file__).resolve().parents[1] / "packages" / "xiaomi_robot_vacuum.yaml"


def _script_block(script_id: str) -> str:
    lines = VACUUM_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script {script_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("   ") and lines[index].endswith(":"):
            end = index
            break

    return "\n".join(lines[start:end])


def test_restore_cleangenius_dismisses_stale_failure_notification_on_success() -> None:
    # Codex P2 on #960: if one run creates x40_cleangenius_restore_failed and
    # a later run successfully restores deep_cleaning, nothing ever
    # dismissed it — the UI kept warning CleanGenius wasn't restored even
    # after the helper verified recovery.
    block = _script_block("x40_ultra_restore_cleangenius")

    assert "action: persistent_notification.create" in block
    assert "notification_id: x40_cleangenius_restore_failed" in block
    assert "action: persistent_notification.dismiss" in block

    dismiss_index = block.index("action: persistent_notification.dismiss")
    dismiss_block = block[dismiss_index : dismiss_index + 200]
    assert "notification_id: x40_cleangenius_restore_failed" in dismiss_block

    else_index = block.index("else:")
    assert else_index < dismiss_index, "dismiss must be on the success (else) branch"
