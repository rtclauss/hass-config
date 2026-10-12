"""The HA reboot watchdog requires private endpoints and an alert destination."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import yaml


ROOT = Path(__file__).resolve().parents[1]
REBOOT_PATH = ROOT / "appdaemon/apps/reboot.py"
APPS_PATH = ROOT / "appdaemon/apps/apps.yaml"


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


def test_appdaemon_config_loads_network_and_device_values_from_secrets() -> None:
    apps = APPS_PATH.read_text()
    examples = (ROOT / "travis_secrets.example.yaml").read_text()
    for key in (
        "private_reboot_probe_primary",
        "private_reboot_probe_secondary",
        "private_reboot_notify_service",
        "private_living_room_remote_eui",
    ):
        assert f"!secret {key}" in apps
        assert f"{key}:" in examples

    values = yaml.safe_load(examples)

    class ExampleSecretLoader(yaml.SafeLoader):
        pass

    ExampleSecretLoader.add_constructor(
        "!secret", lambda loader, node: values[loader.construct_scalar(node)]
    )
    config = yaml.load(apps, Loader=ExampleSecretLoader)
    watchdog = config["Restart HA if network down"]
    assert watchdog["probe_targets"] == ["192.0.2.10:8006", "192.0.2.11:53"]
    assert watchdog["notify_service"] == "notify/example_device"
