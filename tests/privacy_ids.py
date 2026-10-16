"""Identity-neutral references used by config regression tests."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _first(pattern: str, filename: str) -> str:
    match = re.search(pattern, (ROOT / filename).read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise AssertionError(f"Missing expected private identifier in {filename}")
    return match.group(1)


PRESENCE_SLUG = _first(r"^  - id: ([a-z]+)_arrival_emitter$", "packages/zone.yaml")
PRESENCE_SENSOR = f"binary_sensor.bayesian_{PRESENCE_SLUG}_home"
PRESENCE_TRACKER = f"device_tracker.bayesian_{PRESENCE_SLUG}_home"
PRESENCE_BOOLEAN = f"input_boolean.bayesian_{PRESENCE_SLUG}_home"
OWNER_PERSON = "person." + _first(r"person\.([a-z]+)", "packages/home_analyst.yaml")
OWNER_TITLE = OWNER_PERSON.split(".", 1)[1].title()
OWNER_CALENDAR = "calendar." + _first(r"calendar\.([a-z]+_[a-z]+)", "packages/inky_displays.yaml")
DASHBOARD_ROOT = _first(r'url: "/([^/]+)/cleaning-v2"', "packages/water_softener.yaml")
