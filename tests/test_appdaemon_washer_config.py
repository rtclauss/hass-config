from pathlib import Path


APPDAEMON_APPS_PATH = Path(__file__).resolve().parents[1] / "appdaemon" / "apps" / "apps.yaml"
APPDAEMON_WASHER_STATE_MACHINE = (
    Path(__file__).resolve().parents[1] / "appdaemon" / "apps" / "cleaning_machine.py"
)


def test_washing_machine_no_longer_uses_appdaemon_state_machine() -> None:
    config = APPDAEMON_APPS_PATH.read_text()

    assert "washing_machine:" not in config
    assert "module: cleaning_machine" not in config
    assert not APPDAEMON_WASHER_STATE_MACHINE.exists()
