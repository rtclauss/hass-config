"""Tests for the MQTT discovery payload published by room_temp_model_service.

service.py imports paho.mqtt and its sibling `model` via a flat import, so both
are stubbed/pathed here rather than installed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT / "room_temp_model_service"
SERVICE_PATH = SERVICE_DIR / "service.py"
PREEMPTOR_PATH = ROOT / "appdaemon" / "apps" / "thermal_preemptor.py"
SCORER_PATH = ROOT / "appdaemon" / "apps" / "prediction_scorer.py"


def _load_service_module():
    mqtt_mod = types.ModuleType("paho.mqtt.client")
    mqtt_mod.Client = Mock()
    paho = types.ModuleType("paho")
    paho_mqtt = types.ModuleType("paho.mqtt")
    sys.modules.setdefault("paho", paho)
    sys.modules.setdefault("paho.mqtt", paho_mqtt)
    sys.modules["paho.mqtt.client"] = mqtt_mod

    sys.path.insert(0, str(SERVICE_DIR))
    try:
        spec = importlib.util.spec_from_file_location("rtm_service", SERVICE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules["rtm_service"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVICE_DIR))


@pytest.fixture
def service():
    module = _load_service_module()
    svc = module.Service.__new__(module.Service)
    svc.base = "room_temp_model"
    svc.disc_prefix = "homeassistant"
    svc.model = types.SimpleNamespace(rooms={"owner_suite": {}, "office": {}})
    svc.client = Mock()
    return svc


def _discovery_payloads(service):
    service._publish_discovery()
    return {
        call.args[0]: json.loads(call.args[1])
        for call in service.client.publish.call_args_list
    }


def test_discovery_sets_object_id_so_entity_id_matches_consumers(service) -> None:
    # Without object_id, HA slugifies `name` into
    # sensor.predicted_temp_owner_suite_t_30, while ThermalPreemptor and
    # PredictionScorer both read sensor.room_temp_prediction_<room>. unique_id
    # only makes the entity registry-manageable; it does not name it.
    payloads = _discovery_payloads(service)

    for room in ("owner_suite", "office"):
        topic = f"homeassistant/sensor/room_temp_prediction_{room}/config"
        assert topic in payloads
        assert payloads[topic]["object_id"] == f"room_temp_prediction_{room}"


def test_discovery_object_id_matches_the_hard_coded_consumer_entity_ids(service) -> None:
    payloads = _discovery_payloads(service)
    consumers = PREEMPTOR_PATH.read_text(encoding="utf-8") + SCORER_PATH.read_text(encoding="utf-8")

    for cfg in payloads.values():
        entity_id = f"sensor.{cfg['object_id']}"
        # The consumers build this id with an f-string on the room name.
        template = entity_id.replace("_owner_suite", "_{room}").replace("_office", "_{room}")
        assert template in consumers, f"{entity_id} is not what the consumers read"


def test_discovery_keeps_expiry_so_stale_retained_predictions_go_unavailable(service) -> None:
    payloads = _discovery_payloads(service)

    for cfg in payloads.values():
        assert cfg["expire_after"] > 0
