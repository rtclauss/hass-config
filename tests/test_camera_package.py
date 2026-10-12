from __future__ import annotations

from pathlib import Path

import yaml


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))


CAMERA_PATH = Path(__file__).resolve().parents[1] / "packages" / "camera.yaml"


def _automation(automation_id: str) -> dict:
    data = yaml.load(CAMERA_PATH.read_text(encoding="utf-8"), Loader=_Loader)
    return next(a for a in data["automation"] if a["id"] == automation_id)


def test_living_room_animal_detection_notifies_with_cooldown() -> None:
    automation = _automation("living_room_camera_animal_detected_notify")

    assert automation["mode"] == "single"
    assert automation["triggers"][0]["entity_id"] == "event.living_room_camera_object_detected"
    condition = automation["conditions"][0]["value_template"]
    for event_type in ("animal", "dog", "cat"):
        assert f"'{event_type}'" in condition
    assert automation["actions"][0]["action"] == "notify.notify_all"
    assert "delay" in automation["actions"][1]
