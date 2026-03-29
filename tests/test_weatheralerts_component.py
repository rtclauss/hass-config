from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONST_PATH = ROOT / "custom_components" / "weatheralerts" / "const.py"
INIT_PATH = ROOT / "custom_components" / "weatheralerts" / "__init__.py"


def test_weatheralerts_const_module_exists_with_required_defaults() -> None:
    text = CONST_PATH.read_text(encoding="utf-8")

    assert 'DOMAIN = "weatheralerts"' in text
    assert 'ALERTS_API = "https://api.weather.gov/alerts/active?zone={}"' in text
    assert "DEFAULT_UPDATE_INTERVAL = 90" in text
    assert "DEFAULT_API_TIMEOUT = 20" in text
    assert "DEFAULT_EVENT_ICONS" in text


def test_weatheralerts_update_listener_tracks_zone_name_explicitly() -> None:
    text = INIT_PATH.read_text(encoding="utf-8")

    assert "zone_name = entry.options[CONF_ZONE_NAME].strip()" in text
    assert 'zone_name = entry.data.get(CONF_ZONE_NAME, "").strip()' in text
    assert "CONF_ZONE_NAME: zone_name" in text
    assert "title = name or zone_name or f\"NWS {feed_id}\"" in text
