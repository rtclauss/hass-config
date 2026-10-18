"""The HA reboot watchdog requires private endpoints and an alert destination."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REBOOT_PATH = ROOT / "appdaemon/apps/reboot.py"
APPS_TEMPLATE_PATH = ROOT / "private_templates/appdaemon_apps.yaml.tmpl"


def _watchdog(monkeypatch):
    monkeypatch.setitem(sys.modules, "hassapi", SimpleNamespace(Hass=object))
    spec = importlib.util.spec_from_file_location("private_reboot_watchdog", REBOOT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.restart_ha()
    scheduled = []
    app.log = lambda *args, **kwargs: None
    app.run_every = lambda *args, **kwargs: scheduled.append((args, kwargs))
    return app, scheduled


def test_missing_private_probe_configuration_disables_reboot(monkeypatch) -> None:
    app, scheduled = _watchdog(monkeypatch)
    app.args = {}
    app.initialize()
    assert scheduled == []


def test_private_probe_configuration_keeps_watchdog_active(monkeypatch) -> None:
    app, scheduled = _watchdog(monkeypatch)
    app.args = {
        "probe_targets": ["192.0.2.10:8006", "192.0.2.11:53"],
        "notify_service": "notify/example_device",
    }
    app.initialize()
    assert app.targets == [("192.0.2.10", 8006), ("192.0.2.11", 53)]
    assert app.notify_service == "notify/example_device"
    assert len(scheduled) == 1


def test_appdaemon_config_loads_network_and_device_values_from_private_mapping() -> None:
    apps = APPS_TEMPLATE_PATH.read_text()
    examples = json.loads((ROOT / "examples/private_values.example.json").read_text())
    for key in (
        "appdaemon_probe_target_01",
        "appdaemon_probe_target_02",
        "appdaemon_magic_cube_mac_01",
    ):
        assert f"@@PRIVATE:{key}@@" in apps
        assert key in examples
    assert "probe_targets:" in apps
    assert "notify_service:" not in apps.split("Restart HA if network down:", 1)[1].split("\n\n", 1)[0]
