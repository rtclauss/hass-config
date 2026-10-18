from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_instance_profile_and_network_are_private_scalars() -> None:
    config = (ROOT / "configuration.yaml").read_text()
    example = (ROOT / "travis_secrets.example.yaml").read_text()

    for field, key in (
        ("name", "private_home_name"),
        ("unit_system", "private_unit_system"),
        ("currency", "private_currency"),
        ("country", "private_country"),
        ("time_zone", "private_timezone"),
    ):
        assert f"  {field}: !secret {key}" in config
        assert re.search(rf"(?m)^{key}:", example)

    assert "- !secret private_trusted_network_legacy" in config
    assert "private_trusted_network_legacy:" in example
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b", config)
