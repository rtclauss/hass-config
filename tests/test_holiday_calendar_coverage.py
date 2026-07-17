from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "docs" / "holiday_calendar_coverage.md"
HOLIDAYS_PATH = ROOT / "packages" / "holidays.yaml"

COVERAGE_START = date(2026, 5, 29)
COVERAGE_END = date(2028, 5, 29)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(weeks=occurrence - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _in_window(day: date) -> bool:
    return COVERAGE_START <= day <= COVERAGE_END


def _coverage_entries() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []

    for year in range(COVERAGE_START.year, COVERAGE_END.year + 1):
        fixed_dates = {
            "burns_night": date(year, 1, 25),
            "groundhog_day": date(year, 2, 2),
            "leap_day": date(year, 2, 29) if year % 4 == 0 else None,
            "pi_day": date(year, 3, 14),
            "tartan_day": date(year, 4, 6),
            "star_wars_day": date(year, 5, 4),
            "minnesota_statehood_day": date(year, 5, 11),
            "juneteenth": date(year, 6, 19),
            "independence_day": date(year, 7, 4),
            "sealand_independence_day": date(year, 9, 2),
            "talk_like_a_pirate_day": date(year, 9, 19),
            "veterans_day": date(year, 11, 11),
            "halloween": date(year, 10, 31),
            "st_andrews_day": date(year, 11, 30),
            "hogmanay": date(year, 12, 31),
        }

        computed_dates = {
            "presidents_day": _nth_weekday(year, 2, 0, 3),
            "minnesota_fishing_opener": _last_weekday(year, 5, 0) - timedelta(days=16),
            "memorial_day": _last_weekday(year, 5, 0),
            "labor_day": _nth_weekday(year, 9, 0, 1),
            "thanksgiving": _nth_weekday(year, 11, 3, 4),
        }

        for key, day in {**fixed_dates, **computed_dates}.items():
            if day is not None and _in_window(day):
                entries.append((day.isoformat(), key))

        christmas_start = date(year, 12, 1)
        christmas_end = date(year, 12, 31)
        if _in_window(christmas_start) or _in_window(christmas_end):
            entries.append(
                (f"{christmas_start.isoformat()}/{christmas_end.isoformat()}", "christmas_season")
            )

        curling_start = date(year, 1, 1)
        curling_end = date(year, 1, 31)
        if _in_window(curling_start) or _in_window(curling_end):
            entries.append(
                (
                    f"{curling_start.isoformat()}/{curling_end.isoformat()}",
                    "national_curling_month",
                )
            )

    return sorted(entries)


def test_24_month_holiday_coverage_document_lists_every_lighting_observance() -> None:
    coverage_text = COVERAGE_PATH.read_text(encoding="utf-8")
    holidays_text = HOLIDAYS_PATH.read_text(encoding="utf-8")

    assert "Coverage window: 2026-05-29 through 2028-05-29." in coverage_text

    for day_or_range, holiday_key in _coverage_entries():
        assert f"| {day_or_range} | {holiday_key} |" in coverage_text
        assert f'"{holiday_key}": {{' in holidays_text


def test_public_calendar_coverage_expectations_are_documented() -> None:
    coverage_text = COVERAGE_PATH.read_text(encoding="utf-8")

    assert "calendar.mn_holidays" in coverage_text
    assert "observed weekday substitutions" in coverage_text
    assert "intentionally applied every minute" in coverage_text
    assert "declared `cadence_minutes`" in coverage_text
