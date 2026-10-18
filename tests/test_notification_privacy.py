"""Personal notification service ids stay in live secrets or ignored renders."""

from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def test_tracked_packages_use_secret_for_owner_notifications() -> None:
    rendered_outputs = {entry["output"] for entry in json.loads((ROOT / "docs/private_config_manifest.json").read_text(encoding="utf-8"))["files"]}
    for package in (ROOT / "packages").glob("*.yaml"):
        if str(package.relative_to(ROOT)) in rendered_outputs:
            continue
        text = package.read_text(encoding="utf-8")
        assert not re.search(r"\bnotify\.mobile_app_(?!example)[a-z0-9_]+", text), package
    assert "mobile_notify_service_02: notify.mobile_app_example_device_02" in (
        ROOT / "travis_secrets.example.yaml"
    ).read_text(encoding="utf-8")


def test_private_templates_render_the_live_notification_service() -> None:
    templates = list((ROOT / "private_templates").glob("*.tmpl"))
    assert any("@@PRIVATE:mobile_notify_service_01@@" in p.read_text(encoding="utf-8") for p in templates)
    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert not re.search(r"\bnotify\.mobile_app_(?!example)[a-z0-9_]+", text), template
