"""Private renderers must validate inputs before writing any live YAML."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.render_private_config import RenderError, render_all  # noqa: E402


def _fixture(root: Path, files: list[tuple[str, str]], values: dict[str, str]) -> tuple[Path, Path]:
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text("*.yaml\n")
    manifest = root / "manifest.json"
    value_file = root / "private.json"
    manifest.write_text(json.dumps({"version": 1, "files": [
        {"template": source, "output": output} for source, output in files
    ]}))
    value_file.write_text(json.dumps(values))
    return manifest, value_file


def test_render_writes_ignored_yaml_atomically_and_checks_drift(tmp_path: Path) -> None:
    template = tmp_path / "templates" / "package.yaml.tmpl"
    template.parent.mkdir()
    template.write_text('sensor:\n  name: "@@PRIVATE:owner_name@@"\n')
    manifest, values = _fixture(
        tmp_path,
        [("templates/package.yaml.tmpl", "packages/private.yaml")],
        {"owner_name": "Example Owner"},
    )

    assert render_all(tmp_path, manifest, values) == 1
    output = tmp_path / "packages/private.yaml"
    assert output.read_text() == 'sensor:\n  name: "Example Owner"\n'
    assert output.stat().st_mode & 0o777 == 0o600
    assert render_all(tmp_path, manifest, values, check=True) == 1

    output.write_text("stale")
    with pytest.raises(RenderError, match="stale"):
        render_all(tmp_path, manifest, values, check=True)


def test_json_scalar_filter_quotes_private_text(tmp_path: Path) -> None:
    (tmp_path / "input.tmpl").write_text("name: @@PRIVATE:owner_name|json@@\n")
    manifest, values = _fixture(
        tmp_path,
        [("input.tmpl", "output.yaml")],
        {"owner_name": 'Example "Owner"'},
    )

    render_all(tmp_path, manifest, values)
    assert (tmp_path / "output.yaml").read_text() == 'name: "Example \\"Owner\\""\n'


def test_missing_key_blocks_all_outputs_without_exposing_values(tmp_path: Path) -> None:
    (tmp_path / "first.tmpl").write_text("value: @@PRIVATE:present@@\n")
    (tmp_path / "second.tmpl").write_text("value: @@PRIVATE:missing@@\n")
    manifest, values = _fixture(
        tmp_path,
        [("first.tmpl", "first.yaml"), ("second.tmpl", "second.yaml")],
        {"present": "sensitive-but-synthetic"},
    )

    with pytest.raises(RenderError) as failure:
        render_all(tmp_path, manifest, values)
    assert "sensitive-but-synthetic" not in str(failure.value)
    assert not (tmp_path / "first.yaml").exists()
    assert not (tmp_path / "second.yaml").exists()


def test_manifest_cannot_escape_repository(tmp_path: Path) -> None:
    template = tmp_path / "inside.tmpl"
    template.write_text("safe: true\n")
    manifest, values = _fixture(tmp_path, [("inside.tmpl", "../outside.yaml")], {})

    with pytest.raises(RenderError, match="escapes"):
        render_all(tmp_path, manifest, values)


def test_cli_does_not_print_private_values(tmp_path: Path) -> None:
    (tmp_path / "input.tmpl").write_text("token: @@PRIVATE:missing@@\n")
    manifest, values = _fixture(
        tmp_path, [("input.tmpl", "output.yaml")], {"other": "synthetic-private-value"}
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/render_private_config.py"),
         "--root", str(tmp_path), "--manifest", str(manifest), "--values", str(values)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "synthetic-private-value" not in result.stdout + result.stderr
    assert not (tmp_path / "output.yaml").exists()


def test_renderer_rejects_stageable_or_tracked_output(tmp_path: Path) -> None:
    (tmp_path / "input.tmpl").write_text("name: @@PRIVATE:owner_name@@\n")
    manifest, values = _fixture(
        tmp_path, [("input.tmpl", "output.yaml")], {"owner_name": "Synthetic Owner"}
    )
    (tmp_path / ".gitignore").write_text("")
    with pytest.raises(RenderError, match="Git-ignored"):
        render_all(tmp_path, manifest, values)
    assert not (tmp_path / "output.yaml").exists()

    (tmp_path / ".gitignore").write_text("*.yaml\n")
    (tmp_path / "output.yaml").write_text("old\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", "output.yaml"],
        check=True, capture_output=True,
    )
    with pytest.raises(RenderError, match="Git-ignored"):
        render_all(tmp_path, manifest, values)
    assert (tmp_path / "output.yaml").read_text() == "old\n"


def test_normalized_duplicate_outputs_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "one.tmpl").write_text("one: true\n")
    (tmp_path / "two.tmpl").write_text("two: true\n")
    manifest, values = _fixture(
        tmp_path,
        [("one.tmpl", "output.yaml"), ("two.tmpl", "./output.yaml")],
        {},
    )
    with pytest.raises(RenderError, match="Duplicate"):
        render_all(tmp_path, manifest, values)
    assert not (tmp_path / "output.yaml").exists()


def test_committed_manifest_and_examples_validate() -> None:
    assert render_all(
        ROOT,
        ROOT / "docs/private_config_manifest.json",
        ROOT / "examples/private_values.example.json",
        validate=True,
    ) >= 0


def test_missing_only_keeps_existing_private_render(tmp_path: Path) -> None:
    (tmp_path / "first.tmpl").write_text("name: @@PRIVATE:first@@\n")
    (tmp_path / "second.tmpl").write_text("name: @@PRIVATE:second@@\n")
    manifest, values = _fixture(
        tmp_path,
        [("first.tmpl", "first.yaml"), ("second.tmpl", "second.yaml")],
        {"first": "Synthetic first", "second": "Synthetic second"},
    )
    (tmp_path / "first.yaml").write_text("name: Private first\n")

    assert render_all(tmp_path, manifest, values, missing_only=True) == 2
    assert (tmp_path / "first.yaml").read_text() == "name: Private first\n"
    assert (tmp_path / "second.yaml").read_text() == "name: Synthetic second\n"


def test_public_media_template_contains_no_concrete_account_or_device_ids() -> None:
    template = (ROOT / "private_templates/media_player.yaml.tmpl").read_text()
    examples = json.loads((ROOT / "examples/private_values.example.json").read_text())
    assert "@@PRIVATE:media_nfc_tag_id@@" in template
    assert "@@PRIVATE:music_uri_" in template
    assert "@@PRIVATE:media_stream_" in template
    assert len(examples) >= 70
    assert not re.search(
        r"spotify:(?:user:[A-Za-z0-9_.-]+:)?"
        r"(?:playlist|album|track|artist):[A-Za-z0-9]+",
        template,
    )
    assert not re.search(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", template, re.I)
    assert not re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        template,
        re.I,
    )


def test_public_zone_template_keeps_embedded_identity_in_private_mapping() -> None:
    template = (ROOT / "private_templates/zone.yaml.tmpl").read_text()
    examples = json.loads((ROOT / "examples/private_values.example.json").read_text())
    for key in (
        "presence_person_slug",
        "presence_person_title",
        "zone_04_slug",
        "zone_04_label",
        "zone_07_latitude_secret_key",
        "zone_private_annotation_001",
    ):
        assert f"@@PRIVATE:{key}@@" in template
        assert key in examples
    assert len(re.findall(r"@@PRIVATE:zone_\d{2}_slug@@", template)) >= 7


def test_flight_airports_and_home_aliases_are_private() -> None:
    flight = (ROOT / "private_templates/flight_status.yaml.tmpl").read_text()
    trips = (ROOT / "private_templates/trips.yaml.tmpl").read_text()
    examples = json.loads((ROOT / "examples/private_values.example.json").read_text())

    assert len(re.findall(r"@@PRIVATE:airport_map_entry_\d{3}@@", flight)) >= 30
    for key in (
        "home_airport_primary_code",
        "home_airport_secondary_code",
        "home_metro_code",
        "home_city_secondary_code",
        "home_region_code",
    ):
        assert f"@@PRIVATE:{key}@@" in flight
        assert f"@@PRIVATE:{key}@@" in trips
        assert key in examples
    assert "@@PRIVATE:flight_weather_fallback_latitude@@" in flight
    assert "@@PRIVATE:flight_weather_fallback_longitude@@" in flight


def test_appdaemon_identity_and_notification_targets_are_private() -> None:
    apps = (ROOT / "private_templates/appdaemon_apps.yaml.tmpl").read_text()
    vacuum = (ROOT / "private_templates/appdaemon_vacuum_stall_monitor.yaml.tmpl").read_text()
    examples = json.loads((ROOT / "examples/private_values.example.json").read_text())

    for key in (
        "appdaemon_location_source_01",
        "appdaemon_location_source_02",
        "appdaemon_notify_target_slash_01",
        "appdaemon_notify_target_slash_02",
        "appdaemon_probe_target_01",
        "appdaemon_magic_cube_mac_01",
    ):
        assert f"@@PRIVATE:{key}@@" in apps
        assert key in examples
    assert "@@PRIVATE:appdaemon_notify_target_slash_03@@" in vacuum
    assert "@@PRIVATE:owner_person_slug@@" in vacuum
    assert "ios_speed_tracker_entity: @@PRIVATE:appdaemon_location_source_01@@" in apps
    assert "bayesian_device_tracker_friendly_name: \"@@PRIVATE:presence_person_title@@\"" in apps
    assert apps.count("sensor.tomorrow_io_@@PRIVATE:zone_02_name_slug@@") == 5
    assert not re.search(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", apps, re.I)


def test_guest_dashboard_location_is_private() -> None:
    guest = (ROOT / "private_templates/ui-guest.yaml.tmpl").read_text()
    assert "title: @@PRIVATE:zone_02_label@@" in guest
    assert "Time until @@PRIVATE:owner_person_title@@ returns home" in guest
    assert "weather.@@PRIVATE:zone_02_name_slug@@" in guest
    assert "sensor.@@PRIVATE:guest_dashboard_weather_station_slug@@_temperature" in guest
    manifest = json.loads((ROOT / "docs/private_config_manifest.json").read_text())
    assert {"template": "private_templates/ui-guest.yaml.tmpl", "output": "ui-guest.yaml"} in manifest["files"]


def test_vehicle_tiles_and_consumers_use_private_identity() -> None:
    templates = {
        "private_templates/car.yaml.tmpl": ("@@PRIVATE:vehicle_display_name@@",),
        "private_templates/utilities.yaml.tmpl": (
            "@@PRIVATE:owner_person_title@@",
            "@@PRIVATE:owner_person_slug@@",
            "@@PRIVATE:appdaemon_location_source_02@@",
        ),
        "private_templates/plants.yaml.tmpl": ("@@PRIVATE:owner_dashboard_slug@@",),
        "private_templates/tiles_tesla_charging.yaml.tmpl": (
            "@@PRIVATE:owner_person_title@@",
            "@@PRIVATE:owner_person_slug@@",
            "@@PRIVATE:appdaemon_location_source_02@@",
            "@@PRIVATE:vehicle_display_name@@",
        ),
        "private_templates/tiles_tesla_location.yaml.tmpl": (
            "@@PRIVATE:appdaemon_location_source_02@@",
        ),
    }
    for path, markers in templates.items():
        text = (ROOT / path).read_text()
        for marker in markers:
            assert marker in text
    examples = json.loads((ROOT / "examples/private_values.example.json").read_text())
    assert examples["vehicle_display_name"] == "Example Vehicle"
