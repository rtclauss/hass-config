from pathlib import Path


APPDAEMON_APPS_PATH = Path(__file__).resolve().parents[1] / "appdaemon" / "apps" / "apps.yaml"


def test_washing_machine_uses_live_zigbee_door_contact() -> None:
    config = APPDAEMON_APPS_PATH.read_text()

    assert "washing_machine:" in config
    assert (
        "open_sensor: binary_sensor.laundry_room_washing_machine_door_contact"
        in config
    )
    assert "open_sensor: binary_sensor.washer_door" not in config
