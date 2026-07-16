"""MQTT service wrapper around RoomTempModel.

Runs as a standalone container off the Home Assistant host. It is HA-agnostic:
it speaks only MQTT (to the AppDaemon shim + HA discovery) and InfluxDB (for
training). No Home Assistant token or API access required.

Topics (all under MQTT_BASE_TOPIC, default `room_temp_model`):
  <base>/features   (in)  — feature payload from the AppDaemon shim, per cycle:
                            {"ts": iso, "rooms": {name: {room_temp, ...,
                             forecast:{15:{...},30:{...},60:{...}}}}}
  <base>/train      (in)  — retrain trigger (payload optional {"rooms":[...]})
  <base>/status     (out, retained) — service + last-train status JSON

Predictions are published via Home Assistant MQTT discovery so
`sensor.room_temp_prediction_<room>` appear natively:
  homeassistant/sensor/room_temp_prediction_<room>/config  (retained)
  <base>/prediction/<room>                                 (state + attrs)

Training runs on a background thread so the MQTT loop never blocks; only one
training run happens at a time.
"""

import json
import os
import threading

import paho.mqtt.client as mqtt

from model import HORIZONS, RoomTempModel


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def load_config():
    """Config from env + a rooms JSON (ROOMS_JSON or /config/rooms.json)."""
    rooms_json = _env("ROOMS_JSON")
    if rooms_json:
        rooms = json.loads(rooms_json)
    else:
        path = _env("ROOMS_FILE", "/config/rooms.json")
        with open(path) as f:
            rooms = json.load(f)
    return {
        "model_dir": _env("MODEL_DIR", "/models"),
        "latitude": float(_env("LATITUDE", "0")),
        "longitude": float(_env("LONGITUDE", "0")),
        "min_training_samples": int(_env("MIN_TRAINING_SAMPLES", "500")),
        "influxdb": {
            "host": _env("INFLUXDB_HOST", "localhost"),
            "port": int(_env("INFLUXDB_PORT", "8086")),
            "database": _env("INFLUXDB_DATABASE", "home_assistant"),
        },
        "rooms": rooms,
    }


class Service:
    def __init__(self):
        self.cfg = load_config()
        self.base = _env("MQTT_BASE_TOPIC", "room_temp_model")
        self.disc_prefix = _env("MQTT_DISCOVERY_PREFIX", "homeassistant")
        self.model = RoomTempModel(self.cfg)
        self.model.load()
        self._train_lock = threading.Lock()
        self._training = False

        self.client = mqtt.Client(client_id=_env("MQTT_CLIENT_ID", "room_temp_model_service"))
        user = _env("MQTT_USERNAME")
        if user:
            self.client.username_pw_set(user, _env("MQTT_PASSWORD"))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.will_set(f"{self.base}/status", json.dumps({"online": False}), retain=True)

    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(f"{self.base}/features")
        client.subscribe(f"{self.base}/train")
        self._publish_discovery()
        loaded = {r: bool(self.model.models.get(r)) for r in self.model.rooms}
        client.publish(f"{self.base}/status",
                       json.dumps({"online": True, "models_loaded": loaded}), retain=True)

    def _publish_discovery(self):
        for room in self.model.rooms:
            uid = f"room_temp_prediction_{room}"
            cfg = {
                "name": f"Predicted Temp {room.replace('_', ' ').title()} T+30",
                "unique_id": uid,
                # Seed the entity_id explicitly. Without object_id HA slugifies
                # `name` (-> sensor.predicted_temp_owner_suite_t_30), while every
                # consumer (ThermalPreemptor, PredictionScorer) hard-codes
                # sensor.room_temp_prediction_<room>. unique_id only makes the
                # entity registry-manageable; it does not name it.
                "object_id": uid,
                "state_topic": f"{self.base}/prediction/{room}",
                "value_template": "{{ value_json.t30 }}",
                "json_attributes_topic": f"{self.base}/prediction/{room}",
                "unit_of_measurement": "°F",
                "device_class": "temperature",
                # Mark unavailable after 2 missed publish cycles (5-min interval × 2).
                # ThermalPreemptor's _safe_attr_float returns None for unavailable,
                # so stale predictions never trigger a hold.
                "expire_after": 660,
            }
            self.client.publish(f"{self.disc_prefix}/sensor/{uid}/config",
                                json.dumps(cfg), retain=True)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode() or "{}")
        except Exception:
            payload = {}
        if msg.topic == f"{self.base}/features":
            self._handle_features(payload)
        elif msg.topic == f"{self.base}/train":
            self._trigger_train(payload.get("rooms"))

    # ------------------------------------------------------------------

    def _handle_features(self, payload):
        from datetime import datetime, timezone
        ts_raw = payload.get("ts")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.now(timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)
        for room, raw in (payload.get("rooms") or {}).items():
            if room not in self.model.rooms:
                continue
            try:
                result = self.model.predict(room, raw, ts)
            except Exception as e:
                self.client.publish(f"{self.base}/status",
                                    json.dumps({"predict_error": f"{room}: {e}"}))
                continue
            if result is None:
                continue
            result["room"] = room
            result["updated_at"] = ts.isoformat()
            self.client.publish(f"{self.base}/prediction/{room}", json.dumps(result), retain=True)

    def _trigger_train(self, rooms):
        if self._training:
            self.client.publish(f"{self.base}/status", json.dumps({"train": "already_running"}))
            return
        threading.Thread(target=self._run_train, args=(rooms,), daemon=True).start()

    def _run_train(self, rooms):
        with self._train_lock:
            self._training = True
            self.client.publish(f"{self.base}/status", json.dumps({"train": "started", "rooms": rooms}))
            try:
                report = self.model.train(rooms)
                self.client.publish(f"{self.base}/status",
                                    json.dumps({"train": "done", "report": report}), retain=True)
                self._publish_discovery()
            except Exception as e:
                self.client.publish(f"{self.base}/status", json.dumps({"train": "error", "error": str(e)}))
            finally:
                self._training = False

    # ------------------------------------------------------------------

    def run(self):
        host = _env("MQTT_HOST", "localhost")
        port = int(_env("MQTT_PORT", "1883"))
        self.client.connect(host, port, keepalive=60)
        self.client.loop_forever()


if __name__ == "__main__":
    Service().run()
