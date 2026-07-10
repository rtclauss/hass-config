# Room-temperature model service

Trains and serves the per-room temperature-prediction models **off** the Home
Assistant host, so the CPU/memory-heavy training never touches AppDaemon (the
problem that got the AppDaemon bed-side predictor disabled).

It is HA-agnostic: it speaks only **MQTT** and **InfluxDB**. No HA token.

```
AppDaemon shim ──(features)──► MQTT ──► this service ──► GBR model
   (light HA I/O)                          │  trains from InfluxDB
                                           └─(predictions via HA discovery)─► sensor.room_temp_prediction_*
                                                                                   │
                                                          thermal_preemptor + prediction_scorer (unchanged)
```

## What runs where

| Component | Host | Work |
|---|---|---|
| `room_temp_predictor.py` (AppDaemon) | HA host | Thin shim: gather live features + forecasts, publish to MQTT; relay retrain button. No ML libs. |
| **this service** | any Docker host | Training (InfluxDB) + inference; publishes predictions via MQTT discovery. |
| `thermal_preemptor.py`, `prediction_scorer.py` (AppDaemon) | HA host | Unchanged — consume the prediction sensors. |

## MQTT topics

| Topic | Dir | Payload |
|---|---|---|
| `room_temp_model/features` | in | `{"ts": iso, "rooms": {name: {room_temp, room_humidity, outside_temp, outside_humidity, cloud_cover, wind_speed, uv_index, precipitation, occupancy, hvac_heating, hvac_cooling, room_temp_rate_15m, outside_delta_3h, forecast: {"15": {...}, "30": {...}, "60": {...}}}}}` |
| `room_temp_model/train` | in | optional `{"rooms": ["office"]}` (empty = all) |
| `room_temp_model/prediction/<room>` | out (retained) | `{t15,t30,t60,prediction_source,rmse_*_cv_mean,trained_at,...}` |
| `room_temp_model/status` | out (retained) | service + last-train status |
| `homeassistant/sensor/room_temp_prediction_<room>/config` | out (retained) | HA MQTT discovery |

## Deploy

1. Copy `rooms.example.json` → `rooms.json` (already matches the current setup).
2. Fill in `docker-compose.example.yml` (MQTT + InfluxDB reachable from this
   host; lat/lon) and save as `docker-compose.yml`.
3. `docker compose up -d --build`
4. Trigger the first training: press `input_button.retrain_room_temp_models`
   in HA (the shim relays it), or `mosquitto_pub -t room_temp_model/train -m '{}'`.
5. Watch `room_temp_model/status`; once `train: done`, predictions start
   flowing and `sensor.room_temp_prediction_*` populate via discovery.

## Environment variables

`MQTT_HOST` `MQTT_PORT` `MQTT_USERNAME` `MQTT_PASSWORD` `MQTT_BASE_TOPIC`
`MQTT_DISCOVERY_PREFIX` `MQTT_CLIENT_ID` · `INFLUXDB_HOST` `INFLUXDB_PORT`
`INFLUXDB_DATABASE` · `LATITUDE` `LONGITUDE` `MIN_TRAINING_SAMPLES` `MODEL_DIR`
· `ROOMS_FILE` or `ROOMS_JSON`.

## Notes

- Training reads the recorded sensors' history from InfluxDB directly. Feature
  engineering (sun/time/oracle-forecast/coverage-filter) lives in `model.py`
  and is shared by train and inference, so they cannot drift.
- `MODEL_DIR` holds the joblib models; mount it as a volume to survive
  restarts. Point it only at a trusted location (joblib = pickle).
- The shim only *publishes* features; if the service or its host is down,
  predictions simply pause and the preemptor no-ops (it checks for `t60`).
