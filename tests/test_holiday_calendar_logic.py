from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


HOLIDAYS_PATH = Path(__file__).resolve().parents[1] / "packages" / "holidays.yaml"


def _text() -> str:
    return HOLIDAYS_PATH.read_text(encoding="utf-8")


def _template_sensor_block(sensor_name: str) -> str:
    text = _text()
    marker = f"      - name: {sensor_name}"
    start = text.index(marker)
    end_candidates = [
        text.find("\n      - name:", start + 1),
        text.find("\n  - trigger:", start + 1),
    ]
    end_positions = [index for index in end_candidates if index != -1]
    end = min(end_positions) if end_positions else len(text)
    return text[start:end]


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


def _minnesota_fishing_opener(year: int) -> date:
    return _last_weekday(year, 5, 0) - timedelta(days=16)


def test_fixed_date_dynamic_holiday_sensors_exist_with_expected_templates() -> None:
    text = _text()

    expected_snippets = {
        "burns_night": 'state: "{{ now().month == 1 and now().day == 25 }}"',
        "groundhog_day": 'state: "{{ now().month == 2 and now().day == 2 }}"',
        "pi_day": 'state: "{{ now().month == 3 and now().day == 14 }}"',
        "tartan_day": 'state: "{{ now().month == 4 and now().day == 6 }}"',
        "star_wars_day": 'state: "{{ now().month == 5 and now().day == 4 }}"',
        "minnesota_statehood_day": 'state: "{{ now().month == 5 and now().day == 11 }}"',
        "juneteenth": 'state: "{{ now().month == 6 and now().day == 19 }}"',
        "independence_day": 'state: "{{ now().month == 7 and now().day == 4 }}"',
        "sealand_independence_day": 'state: "{{ now().month == 9 and now().day == 2 }}"',
        "talk_like_a_pirate_day": 'state: "{{ now().month == 9 and now().day == 19 }}"',
        "veterans_day": 'state: "{{ now().month == 11 and now().day == 11 }}"',
        "hogmanay": 'state: "{{ now().month == 12 and now().day == 31 }}"',
    }

    for sensor_name, snippet in expected_snippets.items():
        assert f"- name: {sensor_name}" in text
        assert snippet in text


def test_computed_dynamic_holiday_sensors_encode_expected_date_rules() -> None:
    text = _text()

    assert "- name: national_curling_month" in text
    assert 'state: "{{ now().month == 1 }}"' in text

    assert "- name: presidents_day" in text
    assert "15 <= now().day <= 21" in text

    assert "- name: leap_day" in text
    assert 'state: "{{ now().month == 2 and now().day == 29 }}"' in text

    assert "- name: minnesota_fishing_opener" in text
    assert "timedelta(days=16)" in text

    assert "- name: memorial_day" in text
    assert "(now().date() + timedelta(days=7)).month != 5" in text

    assert "- name: labor_day" in text
    assert "1 <= now().day <= 7" in text

    assert "- name: thanksgiving" in text
    assert "22 <= now().day <= 28" in text


def test_reference_dates_for_computed_holidays_match_expected_observances() -> None:
    assert _nth_weekday(2026, 2, 0, 3) == date(2026, 2, 16)
    assert _last_weekday(2026, 5, 0) == date(2026, 5, 25)
    assert _nth_weekday(2026, 9, 0, 1) == date(2026, 9, 7)
    assert _nth_weekday(2026, 11, 3, 4) == date(2026, 11, 26)
    assert _minnesota_fishing_opener(2026) == date(2026, 5, 9)


def test_active_outdoor_holiday_prioritizes_specific_days_over_broader_seasons() -> None:
    block = _template_sensor_block("active_outdoor_holiday")

    assert block.index("binary_sensor.hogmanay") < block.index("binary_sensor.burns_night")
    assert block.index("binary_sensor.burns_night") < block.index(
        "binary_sensor.national_curling_month"
    )


def test_active_holiday_lighting_includes_existing_holidays_after_dynamic_selector() -> None:
    block = _template_sensor_block("active_holiday_lighting")

    assert "states('sensor.active_outdoor_holiday') | trim" in block
    assert block.index("binary_sensor.halloween") < block.index("binary_sensor.st_andrews_day")
    assert block.index("binary_sensor.st_andrews_day") < block.index(
        "binary_sensor.christmas_season"
    )
    assert "Today's special lighting is Christmas Season." in block
    assert "Today's special lighting is Halloween." in block
    assert "Today's special lighting is St Andrew's Day." in block


def test_holiday_lighting_notification_only_sends_on_holiday_days() -> None:
    text = _text()

    assert "- id: notify_holiday_lighting_day" in text
    assert "entity_id: sensor.active_holiday_lighting" not in text
    assert "states('sensor.active_holiday_lighting') | trim not in ['none', 'unknown', 'unavailable', '']" in text
    assert "state_attr('sensor.active_holiday_lighting', 'notification_message')" in text
    assert "action: notify.all" in text
