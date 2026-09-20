from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "packages" / "home_analyst.yaml"
DOC = ROOT / "docs" / "home_analyst.md"


def test_home_analyst_package_has_six_curated_summary_sensors():
    package = PACKAGE.read_text()
    unique_ids = {
        "home_analyst_occupancy_summary",
        "home_analyst_bed_summary",
        "home_analyst_hvac_summary",
        "home_analyst_openings_summary",
        "home_analyst_health_summary",
        "home_analyst_anomaly_summary",
    }
    assert package.count("        unique_id: home_analyst_") == 6
    assert all(f"        unique_id: {unique_id}" in package for unique_id in unique_ids)


def test_home_analyst_is_read_only_and_documents_qwen_setup():
    package = PACKAGE.read_text()
    documentation = DOC.read_text()
    assert "service:" not in package
    assert "qwen3:4b" in documentation
    assert "source_states" in package
    assert "unknown" in documentation
