from pathlib import Path


THEMES_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "packages" / "themes.yaml"


def test_theme_package_tracks_sunrise_and_sunset() -> None:
    text = THEMES_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "id: automatic_theme_change" in text
    assert "trigger: homeassistant" in text
    assert "entity_id: sun.sun" in text
    assert 'to: above_horizon' in text
    assert 'to: below_horizon' in text


def test_theme_package_uses_daytime_theme_above_horizon() -> None:
    text = THEMES_PACKAGE_PATH.read_text(encoding="utf-8")

    assert '{% if states.sun.sun.state == "above_horizon" %}' in text
    assert "ios-light-mode-dark-green" in text


def test_theme_package_randomizes_night_theme_below_horizon() -> None:
    text = THEMES_PACKAGE_PATH.read_text(encoding="utf-8")

    assert "{% else %}" in text

    for theme_name in (
        "ios-dark-mode-dark-green",
        "midnight_blue",
        "noctis-solarized",
        "oxfordblue",
        "slate_red",
        "synthwave",
    ):
        assert theme_name in text

    assert "| random" in text
