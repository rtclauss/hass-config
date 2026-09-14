from __future__ import annotations

from pathlib import Path

from water_meter import watchdog


def test_load_failure_streak_is_zero_when_no_state_file(tmp_path: Path) -> None:
    assert watchdog.load_failure_streak(tmp_path) == 0


def test_record_capture_failure_increments_and_persists(tmp_path: Path) -> None:
    assert watchdog.record_capture_failure(tmp_path) == 1
    assert watchdog.record_capture_failure(tmp_path) == 2
    assert watchdog.record_capture_failure(tmp_path) == 3

    # A fresh read (simulating the next systemd-timer-triggered process)
    # must see the persisted count, not an in-memory one.
    assert watchdog.load_failure_streak(tmp_path) == 3


def test_record_capture_success_resets_the_streak(tmp_path: Path) -> None:
    watchdog.record_capture_failure(tmp_path)
    watchdog.record_capture_failure(tmp_path)

    watchdog.record_capture_success(tmp_path)

    assert watchdog.load_failure_streak(tmp_path) == 0


def test_load_failure_streak_tolerates_corrupt_state_file(tmp_path: Path) -> None:
    path = tmp_path / watchdog.STATE_FILENAME
    path.write_text("not json", encoding="utf-8")

    assert watchdog.load_failure_streak(tmp_path) == 0


def test_load_failure_streak_tolerates_non_mapping_json(tmp_path: Path) -> None:
    path = tmp_path / watchdog.STATE_FILENAME
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert watchdog.load_failure_streak(tmp_path) == 0


def test_load_failure_streak_never_returns_negative(tmp_path: Path) -> None:
    path = tmp_path / watchdog.STATE_FILENAME
    path.write_text('{"consecutive_failures": -5}', encoding="utf-8")

    assert watchdog.load_failure_streak(tmp_path) == 0


def test_should_reboot_compares_against_threshold() -> None:
    assert watchdog.should_reboot(1, threshold=2) is False
    assert watchdog.should_reboot(2, threshold=2) is True
    assert watchdog.should_reboot(3, threshold=2) is True


def test_trigger_reboot_calls_the_reboot_command(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        watchdog.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd)
    )

    watchdog.trigger_reboot()

    assert calls == [["reboot"]]
