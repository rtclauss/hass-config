from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from water_meter import sanity


UTC_NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_first_reading_is_accepted_with_no_last_good() -> None:
    result = sanity.validate_reading(
        "0001234",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=None,
        now=UTC_NOW,
    )

    assert result.accepted is True
    assert result.value == 1234.0
    assert result.stuck is False


@pytest.mark.parametrize("raw_digits", ["12a4567", "", "  12345", "12345.6"])
def test_non_numeric_reads_are_rejected(raw_digits: str) -> None:
    result = sanity.validate_reading(
        raw_digits,
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=None,
        now=UTC_NOW,
    )

    assert result.accepted is False
    assert result.value is None


def test_wrong_digit_count_is_rejected() -> None:
    result = sanity.validate_reading(
        "123",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=None,
        now=UTC_NOW,
    )

    assert result.accepted is False
    assert "digits" in result.reason


def test_decreasing_value_is_rejected() -> None:
    last_good = sanity.LastGoodReading(value=5000.0, timestamp=UTC_NOW.isoformat())

    result = sanity.validate_reading(
        "0004999",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
    )

    assert result.accepted is False
    assert "decreased" in result.reason


def test_implausible_jump_is_rejected() -> None:
    last_good = sanity.LastGoodReading(value=1000.0, timestamp=UTC_NOW.isoformat())

    result = sanity.validate_reading(
        "0002000",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
    )

    assert result.accepted is False
    assert "implausible jump" in result.reason


def test_implausible_jump_allowance_scales_with_elapsed_intervals() -> None:
    # Regression test: comparing accumulated usage against a limit sized for
    # a single interval meant that skipped/rejected polls (a watchdog
    # reboot, a run of OCR failures) made every subsequent real delta look
    # like a bigger "jump" than the one before it, permanently blocking a
    # meter that was actually fine. A jump that's implausible for one
    # 10-minute interval is entirely plausible spread over 5 of them.
    last_good = sanity.LastGoodReading(
        value=1000.0, timestamp=datetime(2026, 8, 28, 11, 10, 0, tzinfo=timezone.utc).isoformat()
    )
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)  # 50 minutes later = 5 intervals

    result = sanity.validate_reading(
        "0002000",  # +1000, implausible for 1 interval (max 500) but not 5 (max 2500)
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=now,
        nominal_interval_seconds=600.0,
    )

    assert result.accepted is True
    assert result.value == 2000.0


def test_implausible_jump_still_rejected_when_it_exceeds_the_scaled_allowance() -> None:
    last_good = sanity.LastGoodReading(
        value=1000.0, timestamp=datetime(2026, 8, 28, 11, 10, 0, tzinfo=timezone.utc).isoformat()
    )
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)  # 50 minutes later = 5 intervals

    result = sanity.validate_reading(
        "0010000",  # +9000, exceeds even the 5-interval allowance of 2500
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=now,
        nominal_interval_seconds=600.0,
    )

    assert result.accepted is False
    assert "implausible jump" in result.reason


def test_elapsed_interval_allowance_never_shrinks_below_one_interval() -> None:
    # A reading that arrives *before* a full nominal interval has passed
    # (e.g. a manual retry seconds after the last accepted run) must not get
    # a smaller allowance than the normal single-interval case.
    last_good = sanity.LastGoodReading(
        value=1000.0, timestamp=datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    )
    now = datetime(2026, 8, 28, 12, 0, 5, tzinfo=timezone.utc)  # 5 seconds later

    result = sanity.validate_reading(
        "0001400",  # +400, within the normal single-interval allowance of 500
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=now,
        nominal_interval_seconds=600.0,
    )

    assert result.accepted is True


def test_plausible_increase_is_accepted() -> None:
    last_good = sanity.LastGoodReading(value=1000.0, timestamp=UTC_NOW.isoformat())

    result = sanity.validate_reading(
        "0001010",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
    )

    assert result.accepted is True
    assert result.value == 1010.0


def test_stuck_flag_set_once_history_window_is_full_and_unchanged() -> None:
    history = tuple([1000.0] * 4)
    last_good = sanity.LastGoodReading(value=1000.0, timestamp=UTC_NOW.isoformat(), history=history)

    # nominal_interval_seconds=720/stuck_after_hours=1.0 -> a 5-sample stuck
    # window (3600/720), matching history_limit so this test isolates the
    # "history window full and unchanged" case on its own.
    result = sanity.validate_reading(
        "0001000",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
        history_limit=5,
        nominal_interval_seconds=720.0,
        stuck_after_hours=1.0,
    )

    assert result.accepted is True
    assert result.stuck is True


def test_stuck_flag_clears_once_value_changes() -> None:
    history = tuple([1000.0] * 4)
    last_good = sanity.LastGoodReading(value=1000.0, timestamp=UTC_NOW.isoformat(), history=history)

    result = sanity.validate_reading(
        "0001005",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
        history_limit=5,
        nominal_interval_seconds=720.0,
        stuck_after_hours=1.0,
    )

    assert result.accepted is True
    assert result.stuck is False


def test_stuck_after_hours_controls_the_window_independent_of_history_limit() -> None:
    # Regression test: stuck detection used to be solely a function of
    # history_limit (a sample count) - with the documented defaults (200
    # samples at a 10-minute cadence) that's really ~33.3 hours, not the
    # configured 24. stuck_after_hours must control the window directly, not
    # just decorate the config file.
    # last_good.history plus this call's own value make up the window, so
    # 1 prior entry + this reading = 2 total (not yet a 3-sample match).
    not_yet_stuck = sanity.validate_reading(
        "0001000",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=sanity.LastGoodReading(
            value=1000.0, timestamp=UTC_NOW.isoformat(), history=(1000.0,)
        ),
        now=UTC_NOW,
        history_limit=200,  # large - must not be what drives "stuck" here
        nominal_interval_seconds=600.0,
        stuck_after_hours=0.5,  # 1800s / 600s = 3-sample window
    )
    assert not_yet_stuck.stuck is False

    # 2 prior entries + this reading = 3 total, completing the window.
    now_stuck = sanity.validate_reading(
        "0001000",
        digit_count=7,
        max_gallons_per_interval=500.0,
        last_good=sanity.LastGoodReading(
            value=1000.0, timestamp=UTC_NOW.isoformat(), history=(1000.0, 1000.0)
        ),
        now=UTC_NOW,
        history_limit=200,
        nominal_interval_seconds=600.0,
        stuck_after_hours=0.5,
    )
    assert now_stuck.stuck is True


def test_last_good_round_trips_through_state_dir(tmp_path: Path) -> None:
    assert sanity.load_last_good(tmp_path) is None

    reading = sanity.LastGoodReading(value=42.0, timestamp=UTC_NOW.isoformat(), history=(1.0, 42.0))
    sanity.save_last_good(tmp_path, reading)

    restored = sanity.load_last_good(tmp_path)
    assert restored == reading


def test_load_last_good_ignores_corrupt_state_file(tmp_path: Path) -> None:
    state_file = tmp_path / sanity.STATE_FILENAME
    state_file.write_text("not json", encoding="utf-8")

    assert sanity.load_last_good(tmp_path) is None


def test_decimal_places_scales_the_raw_digit_string() -> None:
    # Confirmed against real captures of the actual meter: its display has a
    # fixed decimal point before the final digit, so raw "02138978" is really
    # 213897.8 gallons, not 2138978.
    result = sanity.validate_reading(
        "02138978",
        digit_count=8,
        max_gallons_per_interval=500.0,
        last_good=None,
        now=UTC_NOW,
        decimal_places=1,
    )

    assert result.accepted is True
    assert result.value == 213897.8


def test_max_gallons_per_interval_is_compared_in_real_gallons_regardless_of_decimal_places() -> None:
    # The threshold's meaning (max plausible flow per interval) must not
    # silently shift just because decimal_places changed the raw-digit scale.
    last_good = sanity.LastGoodReading(value=213897.8, timestamp=UTC_NOW.isoformat())

    # +0.4 real gallons - trivially plausible - is accepted.
    accepted = sanity.validate_reading(
        "02138982",
        digit_count=8,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
        decimal_places=1,
    )
    assert accepted.accepted is True
    assert accepted.value == 213898.2

    # +1000 real gallons in one interval is implausible and must still be
    # rejected, not silently scaled down by decimal_places first.
    rejected = sanity.validate_reading(
        "02148978",
        digit_count=8,
        max_gallons_per_interval=500.0,
        last_good=last_good,
        now=UTC_NOW,
        decimal_places=1,
    )
    assert rejected.accepted is False
    assert "implausible jump" in rejected.reason


def test_next_last_good_trims_history_to_limit() -> None:
    previous = sanity.LastGoodReading(value=1.0, timestamp=UTC_NOW.isoformat(), history=(1.0, 2.0, 3.0))

    updated = sanity.next_last_good(4.0, previous, history_limit=3, now=UTC_NOW)

    assert updated.value == 4.0
    assert updated.history == (2.0, 3.0, 4.0)
