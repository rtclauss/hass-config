from __future__ import annotations

from pathlib import Path


UTILITIES_PATH = Path(__file__).resolve().parents[1] / "packages" / "utilities.yaml"


def test_gas_price_live_sensor_uses_eia_api_and_guards_missing_data() -> None:
    """Sensor must use the EIA v2 API (issue #385 — way.com returned 403).

    The resource URL is stored in secrets.yaml via !secret eia_gas_price_mn_url so
    the API key is never committed to git. The value_template must gracefully return
    none when the EIA response contains no data rows.
    """
    text = UTILITIES_PATH.read_text(encoding="utf-8")

    assert "name: Woodbury Weekly Regular Gas Price Live" in text
    # EIA API replaces the defunct way.com HTML scrape
    assert "resource: !secret eia_gas_price_mn_url" in text
    assert "api.eia.gov/v2/petroleum/pri/gnd/data/" in text
    # value_template must parse the JSON response and fall back to none
    assert "value_json.get('response'" in text
    assert "data[0]['value'] | float(default=0) | round(2)" in text
    assert "{{ none }}" in text
    # Old way.com scraper must no longer be the REST resource
    assert "resource: https://www.way.com" not in text
    # Old HTML-scrape regex must no longer be in the sensor template
    assert "regex_findall(" not in text
