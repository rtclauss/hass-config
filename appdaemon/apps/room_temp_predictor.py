"""Thin feature-publisher shim for the external room-temperature model service.

The heavy ML (training + inference) now lives in a standalone container
(room_temp_model_service/) that speaks MQTT + InfluxDB — this keeps sklearn /
pandas / astral out of the AppDaemon process (the thread/memory trouble that
got the bed-side predictor disabled).

This app only does light HA I/O:
  * every 5 min, gather each room's live features + a short weather forecast
    and publish them to `<base>/features` over MQTT (via HA's mqtt.publish).
  * relay the retrain button/event to `<base>/train`.

The service predicts and publishes `sensor.room_temp_prediction_<room>` back
via MQTT discovery; thermal_preemptor and prediction_scorer consume those
unchanged. No models, joblib, sklearn, pandas, numpy or astral here.
"""

import json
import math
from datetime import datetime, timedelta, timezone

import hassapi as hass

HORIZONS = [15, 30, 60]

# Hourly-forecast entities in priority order (OpenWeatherMap richest).
FORECAST_ENTITIES = [
    "weather.openweathermap",
    "weather.kmsp",
    "weather.the_brewery",
    "weather.forecast_home",
]

DEFAULT_ROOMS = [
    {"name": "owner_suite",
     "temp_sensors": ["sensor.owner_suite_tph_temperature", "sensor.bedroom_temperature"],
     "humidity_sensors": ["sensor.owner_suite_tph_humidity"],
     "confidence_sensor": "sensor.bedroom_room_confidence"},
    {"name": "office",
     "temp_sensors": ["sensor.office_tph_temperature", "sensor.office_temperature"],
     "humidity_sensors": ["sensor.office_tph_humidity"],
     "confidence_sensor": "sensor.office_room_confidence"},
    {"name": "guest_room",
     "temp_sensors": ["sensor.guest_room_tph_temperature", "sensor.guest_room_temperature"],
     "humidity_sensors": ["sensor.guest_room_tph_humidity"],
     "confidence_sensor": None},
]


class RoomTempPredictor(hass.Hass):
    def initialize(self):
        self.base_topic = self.args.get("mqtt_base_topic", "room_temp_model")
        self.climate_entity = self.args.get("climate_entity", "climate.my_ecobee")
        self.rooms = []
        for entry in (self.args.get("rooms") or DEFAULT_ROOMS):
            sensors = entry.get("temp_sensors")
            if not sensors:
                sensors = [s for s in [entry.get("temp_sensor"), entry.get("temp_fallback")] if s]
            hum = entry.get("humidity_sensors")
            if not hum:
                hum = [s for s in [entry.get("humidity_sensor")] if s]
            self.rooms.append({
                "name": entry["name"],
                "temp_sensors": sensors,
                "humidity_sensors": hum,
                "confidence_sensor": entry.get("confidence_sensor"),
            })

        start = datetime.now(timezone.utc) + timedelta(seconds=30)
        self.run_every(self._publish_features, start, 300)
        self.listen_state(self._on_retrain, "input_button.retrain_room_temp_models")
        self.listen_event(self._on_retrain_event, "retrain_room_temp_models")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value, default=None):
        if value in (None, "unknown", "unavailable", ""):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _avg(self, entities, default=None):
        vals = [self._safe_float(self.get_state(e)) for e in entities]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else default

    def _first(self, entities, default=None):
        for e in entities:
            v = self._safe_float(self.get_state(e))
            if v is not None:
                return v
        return default

    def _avg_history_slope(self, entities, minutes=30):
        """Average slope across all available sensors — matches the averaged room_temp feature."""
        slopes = [self._history_slope(e, minutes) for e in entities]
        slopes = [s for s in slopes if s is not None]
        return sum(slopes) / len(slopes) if slopes else 0.0

    def _history_slope(self, entity_id, minutes=30):
        """°F/min slope from recent history (no numpy — plain least squares)."""
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=minutes)
            hist = self.get_history(entity_id=entity_id, start_time=start, end_time=end)
            if not hist or not hist[0]:
                return 0.0
            pts = [(i, float(s["state"])) for i, s in enumerate(hist[0])
                   if s.get("state") not in (None, "unknown", "unavailable", "")]
            if len(pts) < 2:
                return 0.0
            n = len(pts)
            sx = sum(x for x, _ in pts)
            sy = sum(y for _, y in pts)
            sxx = sum(x * x for x, _ in pts)
            sxy = sum(x * y for x, y in pts)
            denom = n * sxx - sx * sx
            if denom == 0:
                return 0.0
            slope_per_step = (n * sxy - sx * sy) / denom
            return slope_per_step * (n / minutes)  # per-step -> per-minute
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Weather forecast (OWM-first hourly)
    # ------------------------------------------------------------------

    def _forecasts(self):
        entries = []
        for entity_id in FORECAST_ENTITIES:
            try:
                raw = self.call_service("weather/get_forecasts", entity_id=entity_id,
                                        type="hourly", return_response=True)
                e = (raw or {}).get(entity_id, {}).get("forecast", [])
                if e:
                    entries = e
                    break
            except Exception:
                continue
        now = datetime.now(timezone.utc)
        by_min = {}
        for entry in entries:
            try:
                dt = datetime.fromisoformat(entry["datetime"].replace("Z", "+00:00"))
                by_min[int((dt - now).total_seconds() / 60)] = entry
            except Exception:
                continue
        out = {}
        for h in HORIZONS:
            if not by_min:
                out[str(h)] = {}
                continue
            key = min(by_min.keys(), key=lambda k: abs(k - h))
            fc = by_min[key] if abs(key - h) <= 90 else {}
            out[str(h)] = {
                "temperature": fc.get("temperature"),
                "humidity": fc.get("humidity"),
                "cloud_cover": fc.get("cloud_coverage"),
                "wind_speed": fc.get("wind_speed"),
                "uv_index": fc.get("uv_index"),
                "precipitation": fc.get("precipitation"),
            }
        return out

    # ------------------------------------------------------------------
    # Publish loop
    # ------------------------------------------------------------------

    def _publish_features(self, kwargs):
        hvac_action = (self.get_state(self.climate_entity, attribute="hvac_action") or "").lower()
        hvac_heating = 1.0 if "heat" in hvac_action else 0.0
        hvac_cooling = 1.0 if "cool" in hvac_action else 0.0

        outside_temp = self._first(["sensor.canonical_outside_temperature", "sensor.outside_temperature"])
        outside_humidity = self._first(["sensor.canonical_outside_humidity", "sensor.outside_humidity"])
        cloud_cover = self._first(["sensor.canonical_cloud_cover", "sensor.tomorrow_io_the_brewery_cloud_cover"])
        wind_speed = self._safe_float(self.get_state("sensor.canonical_wind_speed"))
        uv_index = self._safe_float(self.get_state("sensor.canonical_uv_index"))
        precipitation = self._safe_float(self.get_state("sensor.canonical_precipitation"))
        outside_delta_3h = self._history_slope("sensor.canonical_outside_temperature", 180) * 180
        forecast = self._forecasts()

        rooms = {}
        for cfg in self.rooms:
            temp = self._avg(cfg["temp_sensors"])
            if temp is None:
                continue
            conf = cfg["confidence_sensor"]
            rooms[cfg["name"]] = {
                "room_temp": temp,
                "room_humidity": self._avg(cfg["humidity_sensors"]) if cfg["humidity_sensors"] else None,
                "outside_temp": outside_temp,
                "outside_humidity": outside_humidity,
                "cloud_cover": cloud_cover,
                "wind_speed": wind_speed,
                "uv_index": uv_index,
                "precipitation": precipitation,
                "occupancy": self._safe_float(self.get_state(conf), 0) if conf else 0,
                "hvac_heating": hvac_heating,
                "hvac_cooling": hvac_cooling,
                "room_temp_rate_15m": self._avg_history_slope(cfg["temp_sensors"], 15),
                "outside_delta_3h": outside_delta_3h,
                "forecast": forecast,
            }

        if not rooms:
            return
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "rooms": rooms}
        self.call_service("mqtt/publish", topic=f"{self.base_topic}/features",
                          payload=json.dumps(payload))

    # ------------------------------------------------------------------
    # Retrain relay
    # ------------------------------------------------------------------

    def _on_retrain(self, entity, attribute, old, new, kwargs):
        self._relay_train()

    def _on_retrain_event(self, event_name, data, kwargs):
        self._relay_train()

    def _relay_train(self):
        self.log("Relaying retrain trigger to model service")
        self.call_service("mqtt/publish", topic=f"{self.base_topic}/train", payload="{}")
