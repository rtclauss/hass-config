"""Predictive per-room temperature app using GradientBoostingRegressor.

Training data comes from InfluxDB (multi-year history). Models are saved as
joblib files and loaded at startup. Retrain is triggered manually via
input_button.retrain_room_temp_models or the event 'retrain_room_temp_models'.
Every 5 minutes the prediction loop publishes sensor.room_temp_prediction_<room>
with t15/t30/t60 attributes.
"""

import math
import os
from datetime import datetime, timedelta, timezone

import hassapi as hass

HORIZONS = [15, 30, 60]
SLOT_MIN = 5
HORIZON_SLOTS = {h: h // SLOT_MIN for h in HORIZONS}
PURGE_SLOTS = 48  # 4-hour autocorrelation purge at fold boundaries

ROOMS = {
    "owner_suite": {
        "temp_sensor": "sensor.owner_suite_tph_temperature",
        "confidence_sensor": "sensor.bedroom_room_confidence",
    },
    "office": {
        "temp_sensor": "sensor.office_tph_temperature",
        "confidence_sensor": "sensor.office_room_confidence",
    },
    "guest_room": {
        "temp_sensor": "sensor.guest_room_tph_temperature",
        "confidence_sensor": None,
    },
}


class RoomTempPredictor(hass.Hass):
    def initialize(self):
        self.model_dir = self.args.get("model_dir", "/config/appdaemon/models")
        self.min_samples = int(self.args.get("min_training_samples", 500))
        self.influxdb_host = self.args.get("influxdb_host", "localhost")
        self.influxdb_port = int(self.args.get("influxdb_port", 8086))
        self.influxdb_db = self.args.get("influxdb_database", "home_assistant")

        self.models = {room: {} for room in ROOMS}
        self.train_meta = {room: {} for room in ROOMS}

        os.makedirs(self.model_dir, exist_ok=True)
        self._load_models_from_disk()

        start = datetime.now(timezone.utc) + timedelta(seconds=30)
        self.run_every(self._update_predictions, start, 300)

        self.listen_state(self._on_retrain_button, "input_button.retrain_room_temp_models")
        self.listen_event(self._on_retrain_event, "retrain_room_temp_models")

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------

    def _model_path(self, room, horizon):
        return os.path.join(self.model_dir, f"room_temp_{room}_{horizon}m.joblib")

    def _load_models_from_disk(self):
        try:
            import joblib
        except ImportError:
            self.log("joblib not available; starting with linear fallback", level="WARNING")
            return
        for room in ROOMS:
            loaded = {}
            for h in HORIZONS:
                path = self._model_path(room, h)
                if os.path.exists(path):
                    try:
                        loaded[h] = joblib.load(path)
                    except Exception as e:
                        self.log(f"Failed to load model {path}: {e}", level="WARNING")
            if loaded:
                self.models[room] = loaded
                meta_path = self._model_path(room, "meta").replace(".joblib", ".json")
                if os.path.exists(meta_path):
                    import json
                    with open(meta_path) as f:
                        self.train_meta[room] = json.load(f)
                self.log(f"Loaded {len(loaded)} models for {room}")

    def _save_meta(self, room, meta):
        import json
        meta_path = self._model_path(room, "meta").replace(".joblib", ".json")
        with open(meta_path, "w") as f:
            json.dump(meta, f)

    # ------------------------------------------------------------------
    # InfluxDB helpers
    # ------------------------------------------------------------------

    def _influx_client(self):
        from influxdb import InfluxDBClient
        return InfluxDBClient(
            host=self.influxdb_host,
            port=self.influxdb_port,
            database=self.influxdb_db,
        )

    def _query_series(self, client, entity_id, start_days=730):
        """Return a pandas Series of numeric state values resampled to 5-min grid."""
        import pandas as pd
        start_str = (datetime.utcnow() - timedelta(days=start_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Try °F measurement first (room temps), then unitless/% for ratios
        for measurement in ['"°F"', '"%" ', '"W/m²"', '/.*/']:
            q = (
                f'SELECT value FROM {measurement} '
                f"WHERE entity_id='{entity_id}' AND time>='{start_str}' "
                f"ORDER BY time ASC"
            )
            try:
                result = client.query(q)
                points = list(result.get_points())
                if points:
                    df = pd.DataFrame(points)
                    df["time"] = pd.to_datetime(df["time"])
                    df = df.set_index("time").sort_index()
                    series = df["value"].astype(float)
                    return series.resample("5min").mean().ffill(limit=12)
            except Exception:
                continue
        return None

    def _query_generic(self, client, entity_id, start_days=730):
        """Query any numeric entity regardless of measurement name."""
        import pandas as pd
        start_str = (datetime.utcnow() - timedelta(days=start_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = (
            f"SELECT value FROM /.*/ "
            f"WHERE entity_id='{entity_id}' AND time>='{start_str}' "
            f"ORDER BY time ASC"
        )
        try:
            result = client.query(q)
            all_points = []
            for _key, points in result.items():
                all_points.extend(list(points))
            if not all_points:
                return None
            df = pd.DataFrame(all_points)
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time").sort_index()
            if "value" not in df.columns:
                return None
            series = df["value"].astype(float)
            return series.resample("5min").mean().ffill(limit=12)
        except Exception as e:
            self.log(f"InfluxDB query failed for {entity_id}: {e}", level="WARNING")
            return None

    # ------------------------------------------------------------------
    # Sun position computation via astral
    # ------------------------------------------------------------------

    @staticmethod
    def _sun_position(lat, lon, dt):
        """Return (elevation_deg, azimuth_deg) for a UTC datetime."""
        try:
            from astral import LocationInfo
            from astral.sun import sun as astral_sun
            loc = LocationInfo(latitude=lat, longitude=lon)
            s = astral_sun(loc.observer, date=dt.date(), tzinfo=timezone.utc)
            # astral doesn't give elevation directly from sun(); use formula
            import math as _math
            # Solar elevation via simple formula as fallback
            # Use astral's SolarAltitude if available
            try:
                from astral.sun import elevation as astral_elevation
                from astral.sun import azimuth as astral_azimuth
                elev = astral_elevation(loc.observer, dt)
                azim = astral_azimuth(loc.observer, dt)
                return float(elev), float(azim)
            except ImportError:
                pass
        except ImportError:
            pass
        # Pure-math fallback (approximate, good to ~1°)
        import math as _math
        lat_r = _math.radians(lat)
        doy = dt.timetuple().tm_yday
        hour_utc = dt.hour + dt.minute / 60.0
        # Solar declination
        decl = _math.radians(23.45 * _math.sin(_math.radians(360 / 365 * (doy - 81))))
        # Hour angle (approximate: no equation-of-time, lon offset)
        hour_angle = _math.radians(15 * (hour_utc + lon / 15 - 12))
        sin_elev = (_math.sin(lat_r) * _math.sin(decl)
                    + _math.cos(lat_r) * _math.cos(decl) * _math.cos(hour_angle))
        elev = _math.degrees(_math.asin(max(-1.0, min(1.0, sin_elev))))
        cos_az = (_math.sin(decl) - _math.sin(_math.radians(elev)) * _math.sin(lat_r)) / (
            _math.cos(_math.radians(elev)) * _math.cos(lat_r) + 1e-9
        )
        azim = _math.degrees(_math.acos(max(-1.0, min(1.0, cos_az))))
        if _math.sin(hour_angle) > 0:
            azim = 360 - azim
        return elev, azim

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _build_training_data(self, room, cfg):
        import numpy as np
        import pandas as pd

        client = self._influx_client()
        lat = float(self.AD.config.latitude)
        lon = float(self.AD.config.longitude)

        # ---- pull raw series ----
        room_temp = self._query_generic(client, cfg["temp_sensor"])
        if room_temp is None or len(room_temp) < self.min_samples:
            self.log(f"{room}: insufficient room_temp data", level="WARNING")
            return None, None

        outside_temp = self._query_generic(client, "sensor.outside_temperature") or pd.Series(dtype=float)
        outside_humidity = self._query_generic(client, "sensor.outside_humidity") or pd.Series(dtype=float)
        cloud_cover = self._query_generic(client, "sensor.tomorrow_io_the_brewery_cloud_cover") or pd.Series(dtype=float)
        wind_speed = self._query_generic(client, "sensor.tomorrow_io_the_brewery_wind_speed") or pd.Series(dtype=float)
        wind_bearing = self._query_generic(client, "sensor.tomorrow_io_the_brewery_wind_direction") or pd.Series(dtype=float)
        precipitation = self._query_generic(client, "sensor.tomorrow_io_the_brewery_precipitation_intensity") or pd.Series(dtype=float)
        hvac_series = self._query_generic(client, "sensor.hvac_activity") or pd.Series(dtype=float)

        if cfg["confidence_sensor"]:
            confidence = self._query_generic(client, cfg["confidence_sensor"]) or pd.Series(dtype=float)
        else:
            confidence = pd.Series(dtype=float)

        # ---- align to room_temp index ----
        idx = room_temp.index
        df = pd.DataFrame({"room_temp": room_temp}, index=idx)
        df["outside_temp"] = outside_temp.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["outside_humidity"] = outside_humidity.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["cloud_cover"] = cloud_cover.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["wind_speed"] = wind_speed.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["wind_bearing"] = wind_bearing.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["precipitation"] = precipitation.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["occupancy"] = confidence.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min")).fillna(0)

        # HVAC: encode as hvac_heating / hvac_cooling booleans
        hvac_str = hvac_series.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))
        df["hvac_heating"] = (hvac_str == "heating").astype(float)
        df["hvac_cooling"] = (hvac_str == "cooling").astype(float)

        # ---- engineered features ----
        # 15-min rolling OLS rate (3-slot window)
        df["room_temp_rate_15m"] = (
            df["room_temp"].rolling(3, min_periods=2)
            .apply(lambda x: np.polyfit(range(len(x)), x, 1)[0] if len(x) >= 2 else 0, raw=True)
        )
        # 3-hour outside temp delta
        df["outside_delta_3h"] = df["outside_temp"].diff(36)

        # Cyclic wind bearing
        wb_rad = np.radians(df["wind_bearing"].fillna(0))
        df["wind_bearing_sin"] = np.sin(wb_rad)
        df["wind_bearing_cos"] = np.cos(wb_rad)

        # Time cyclic features
        hours = df.index.hour + df.index.minute / 60.0
        doy = df.index.dayofyear
        df["hour_sin"] = np.sin(2 * np.pi * hours / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hours / 24)
        df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
        df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

        # Sun position via astral for each timestamp (vectorized as apply)
        def sun_features(ts):
            dt = ts.to_pydatetime().replace(tzinfo=timezone.utc)
            elev, azim = self._sun_position(lat, lon, dt)
            return elev, azim

        sun_vals = [sun_features(ts) for ts in df.index]
        df["sun_elevation"] = [v[0] for v in sun_vals]
        df["sun_azimuth_sin"] = np.sin(np.radians([v[1] for v in sun_vals]))
        df["sun_azimuth_cos"] = np.cos(np.radians([v[1] for v in sun_vals]))

        # ---- oracle forecast features (actual t+N observations as training proxy) ----
        for h, slots in HORIZON_SLOTS.items():
            df[f"cloud_cover_{h}m"] = df["cloud_cover"].shift(-slots)
            df[f"outside_temp_{h}m"] = df["outside_temp"].shift(-slots)
            df[f"outside_humidity_{h}m"] = df["outside_humidity"].shift(-slots)
            df[f"precipitation_{h}m"] = df["precipitation"].shift(-slots)
            df[f"wind_speed_{h}m"] = df["wind_speed"].shift(-slots)
            wb_shifted = df["wind_bearing"].shift(-slots).fillna(0)
            wb_shifted_rad = np.radians(wb_shifted)
            df[f"wind_bearing_sin_{h}m"] = np.sin(wb_shifted_rad)
            df[f"wind_bearing_cos_{h}m"] = np.cos(wb_shifted_rad)
            sun_future = []
            for ts in df.index:
                dt_f = (ts + timedelta(minutes=h)).to_pydatetime().replace(tzinfo=timezone.utc)
                elev_f, azim_f = self._sun_position(lat, lon, dt_f)
                sun_future.append((elev_f, azim_f))
            df[f"sun_elevation_{h}m"] = [v[0] for v in sun_future]
            df[f"sun_azimuth_sin_{h}m"] = np.sin(np.radians([v[1] for v in sun_future]))
            df[f"sun_azimuth_cos_{h}m"] = np.cos(np.radians([v[1] for v in sun_future]))

        # ---- targets ----
        y_dict = {}
        for h, slots in HORIZON_SLOTS.items():
            future_temp = df["room_temp"].shift(-slots)
            y_dict[f"delta_{h}"] = future_temp - df["room_temp"]

        # ---- interleaved week CV fold assignment ----
        df["fold"] = df.index.isocalendar().week % 5

        df = df.dropna()
        if len(df) < self.min_samples:
            self.log(f"{room}: only {len(df)} clean samples after dropna", level="WARNING")
            return None, None

        return df, y_dict

    def _train_for_room(self, room, cfg):
        try:
            import joblib
            import numpy as np
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.metrics import mean_squared_error
        except ImportError as e:
            self.log(f"Missing ML dependency: {e}", level="ERROR")
            return {}, {}

        self.log(f"Starting training for {room}...")
        df, y_dict = self._build_training_data(room, cfg)
        if df is None:
            return {}, {}

        feature_cols = [c for c in df.columns if c not in ("fold",) and not c.startswith("delta_")]

        room_models = {}
        metrics = {}

        for h in HORIZONS:
            y = y_dict[f"delta_{h}"]
            y = y.reindex(df.index)

            # 5-fold purged interleaved CV for evaluation
            cv_rmses = []
            for fold_k in range(5):
                test_mask = df["fold"] == fold_k
                # purge: drop rows within PURGE_SLOTS of any fold-boundary crossing
                test_positions = df.index[test_mask]
                if len(test_positions) == 0:
                    continue
                purge_set = set()
                for i, idx_val in enumerate(df.index):
                    if test_mask.iloc[i]:
                        for j in range(max(0, i - PURGE_SLOTS), min(len(df), i + PURGE_SLOTS + 1)):
                            if j != i:
                                purge_set.add(df.index[j])
                keep = ~df.index.isin(purge_set)
                train_mask = keep & (df["fold"] != fold_k)
                if train_mask.sum() < 100 or test_mask.sum() < 10:
                    continue
                X_tr = df.loc[train_mask, feature_cols]
                y_tr = y[train_mask]
                X_te = df.loc[test_mask, feature_cols]
                y_te = y[test_mask]
                m = GradientBoostingRegressor(
                    n_estimators=100, max_depth=4, min_samples_leaf=20, random_state=42
                )
                m.fit(X_tr, y_tr)
                preds = m.predict(X_te)
                cv_rmses.append(math.sqrt(mean_squared_error(y_te, preds)))

            cv_mean = round(float(np.mean(cv_rmses)), 3) if cv_rmses else None
            cv_std = round(float(np.std(cv_rmses)), 3) if cv_rmses else None

            # Final model trained on all data
            X_all = df[feature_cols]
            y_all = y
            final_model = GradientBoostingRegressor(
                n_estimators=100, max_depth=4, min_samples_leaf=20, random_state=42
            )
            final_model.fit(X_all, y_all)
            joblib.dump(final_model, self._model_path(room, h))
            room_models[h] = final_model
            metrics[f"rmse_{h}m_cv_mean"] = cv_mean
            metrics[f"rmse_{h}m_cv_std"] = cv_std
            self.log(f"{room} T+{h}m CV RMSE: {cv_mean} ± {cv_std}")

        metrics["trained_at"] = datetime.utcnow().isoformat()
        metrics["n_samples"] = len(df)
        metrics["feature_cols"] = feature_cols
        self._save_meta(room, metrics)
        return room_models, metrics

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    def _get_weather_forecasts(self):
        """Return dict: horizon_minutes -> {cloud_cover, temperature, precipitation, wind_speed, wind_bearing, humidity}."""
        try:
            raw = self.call_service(
                "weather/get_forecasts",
                entity_id="weather.tomorrow_io_the_brewery_daily",
                type="hourly",
                return_response=True,
            )
            forecasts = raw.get("weather.tomorrow_io_the_brewery_daily", {}).get("forecast", [])
        except Exception:
            return {}

        now = datetime.now(timezone.utc)
        result = {}
        for entry in forecasts:
            try:
                dt_str = entry.get("datetime")
                if not dt_str:
                    continue
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                minutes_ahead = int((dt - now).total_seconds() / 60)
                result[minutes_ahead] = {
                    "cloud_cover": entry.get("cloud_coverage"),
                    "temperature": entry.get("temperature"),
                    "precipitation": entry.get("precipitation"),
                    "wind_speed": entry.get("wind_speed"),
                    "wind_bearing": entry.get("wind_bearing"),
                    "humidity": entry.get("humidity"),
                }
            except Exception:
                continue
        return result

    def _nearest_forecast(self, forecasts, horizon_min):
        """Pick the forecast entry closest to horizon_min."""
        if not forecasts:
            return {}
        best_key = min(forecasts.keys(), key=lambda k: abs(k - horizon_min))
        if abs(best_key - horizon_min) > 90:
            return {}
        return forecasts[best_key]

    def _get_history_slope(self, entity_id, minutes=30):
        """Return °F/min slope from recent history, or 0.0 on failure."""
        try:
            import numpy as np
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=minutes)
            hist = self.get_history(entity_id=entity_id, start_time=start, end_time=end)
            if not hist or not hist[0]:
                return 0.0
            points = [(i, float(s["state"])) for i, s in enumerate(hist[0])
                      if s.get("state") not in (None, "unknown", "unavailable", "")]
            if len(points) < 2:
                return 0.0
            xs, ys = zip(*points)
            coeffs = np.polyfit(xs, ys, 1)
            # slope is per-index-step; convert to per minute (approx steps are every 5 min)
            steps_per_min = len(points) / minutes
            return float(coeffs[0]) * steps_per_min
        except Exception:
            return 0.0

    def _build_current_features(self, room, cfg, forecasts, lat, lon):
        """Build single-row feature dict for inference."""
        import numpy as np

        def safe_float(val, default=None):
            if val in (None, "unknown", "unavailable", ""):
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        now = datetime.now(timezone.utc)
        room_temp = safe_float(self.get_state(cfg["temp_sensor"]))
        outside_temp = safe_float(self.get_state("sensor.outside_temperature"))
        outside_humidity = safe_float(self.get_state("sensor.outside_humidity"))
        cloud_cover = safe_float(self.get_state("sensor.tomorrow_io_the_brewery_cloud_cover"))
        wind_speed = safe_float(self.get_state("sensor.tomorrow_io_the_brewery_wind_speed"))
        wind_bearing = safe_float(self.get_state("sensor.tomorrow_io_the_brewery_wind_direction"), 0)
        precipitation = safe_float(self.get_state("sensor.tomorrow_io_the_brewery_precipitation_intensity"), 0)
        occupancy = safe_float(self.get_state(cfg["confidence_sensor"]) if cfg["confidence_sensor"] else None, 0)

        hvac_action = self.get_state("climate.my_ecobee", attribute="hvac_action") or ""
        hvac_heating = 1.0 if "heat" in hvac_action.lower() else 0.0
        hvac_cooling = 1.0 if "cool" in hvac_action.lower() else 0.0

        slope = self._get_history_slope(cfg["temp_sensor"], 15)
        outside_delta_3h = self._get_history_slope("sensor.outside_temperature", 180) * 180

        elev, azim = self._sun_position(lat, lon, now)
        hours = now.hour + now.minute / 60.0
        doy = now.timetuple().tm_yday
        wb_rad = math.radians(wind_bearing or 0)

        row = {
            "room_temp": room_temp,
            "outside_temp": outside_temp,
            "outside_humidity": outside_humidity,
            "cloud_cover": cloud_cover,
            "wind_speed": wind_speed,
            "wind_bearing": wind_bearing,
            "precipitation": precipitation,
            "occupancy": occupancy,
            "hvac_heating": hvac_heating,
            "hvac_cooling": hvac_cooling,
            "room_temp_rate_15m": slope,
            "outside_delta_3h": outside_delta_3h,
            "wind_bearing_sin": math.sin(wb_rad),
            "wind_bearing_cos": math.cos(wb_rad),
            "hour_sin": math.sin(2 * math.pi * hours / 24),
            "hour_cos": math.cos(2 * math.pi * hours / 24),
            "doy_sin": math.sin(2 * math.pi * doy / 365.25),
            "doy_cos": math.cos(2 * math.pi * doy / 365.25),
            "sun_elevation": elev,
            "sun_azimuth_sin": math.sin(math.radians(azim)),
            "sun_azimuth_cos": math.cos(math.radians(azim)),
        }

        for h in HORIZONS:
            fc = self._nearest_forecast(forecasts, h)
            fc_wb = fc.get("wind_bearing") or 0
            fc_wb_rad = math.radians(fc_wb)
            elev_f, azim_f = self._sun_position(lat, lon, now + timedelta(minutes=h))
            row[f"cloud_cover_{h}m"] = fc.get("cloud_cover", cloud_cover)
            row[f"outside_temp_{h}m"] = fc.get("temperature", outside_temp)
            row[f"outside_humidity_{h}m"] = fc.get("humidity", outside_humidity)
            row[f"precipitation_{h}m"] = fc.get("precipitation", precipitation)
            row[f"wind_speed_{h}m"] = fc.get("wind_speed", wind_speed)
            row[f"wind_bearing_sin_{h}m"] = math.sin(fc_wb_rad)
            row[f"wind_bearing_cos_{h}m"] = math.cos(fc_wb_rad)
            row[f"sun_elevation_{h}m"] = elev_f
            row[f"sun_azimuth_sin_{h}m"] = math.sin(math.radians(azim_f))
            row[f"sun_azimuth_cos_{h}m"] = math.cos(math.radians(azim_f))

        return row, room_temp

    def _linear_rate_fallback(self, temp_sensor):
        return self._get_history_slope(temp_sensor, 30)

    # ------------------------------------------------------------------
    # Prediction loop
    # ------------------------------------------------------------------

    def _update_predictions(self, kwargs):
        try:
            lat = float(self.AD.config.latitude)
            lon = float(self.AD.config.longitude)
        except Exception:
            lat, lon = 0.0, 0.0

        forecasts = self._get_weather_forecasts()

        for room, cfg in ROOMS.items():
            try:
                room_models = self.models.get(room, {})
                meta = self.train_meta.get(room, {})

                if not room_models:
                    rate = self._linear_rate_fallback(cfg["temp_sensor"])
                    current_temp_raw = self.get_state(cfg["temp_sensor"])
                    if current_temp_raw in (None, "unknown", "unavailable"):
                        continue
                    current_temp = float(current_temp_raw)
                    t15 = current_temp + rate * 15
                    t30 = current_temp + rate * 30
                    t60 = current_temp + rate * 60
                    source = "fallback_linear"
                else:
                    row, current_temp = self._build_current_features(room, cfg, forecasts, lat, lon)
                    if current_temp is None:
                        continue
                    feature_cols = meta.get("feature_cols")
                    if feature_cols:
                        import pandas as pd
                        X = pd.DataFrame([row])[feature_cols].fillna(0)
                        feat = X.values[0]
                    else:
                        import numpy as np
                        feat = [row.get(k, 0) or 0 for k in sorted(row.keys())]
                    t15 = current_temp + float(room_models[15].predict([feat])[0])
                    t30 = current_temp + float(room_models[30].predict([feat])[0])
                    t60 = current_temp + float(room_models[60].predict([feat])[0])
                    source = "gbr_model"

                self.set_state(
                    f"sensor.room_temp_prediction_{room}",
                    state=round(t30, 1),
                    attributes={
                        "t15": round(t15, 2),
                        "t30": round(t30, 2),
                        "t60": round(t60, 2),
                        "prediction_source": source,
                        "trained_at": meta.get("trained_at"),
                        "rmse_15m_cv_mean": meta.get("rmse_15m_cv_mean"),
                        "rmse_30m_cv_mean": meta.get("rmse_30m_cv_mean"),
                        "rmse_60m_cv_mean": meta.get("rmse_60m_cv_mean"),
                        "n_training_samples": meta.get("n_samples"),
                        "unit_of_measurement": "°F",
                        "friendly_name": f"Predicted Temp {room.replace('_', ' ').title()} T+30",
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                self.log(f"Prediction error for {room}: {e}", level="WARNING")

    # ------------------------------------------------------------------
    # Retrain triggers
    # ------------------------------------------------------------------

    def _on_retrain_button(self, entity, attribute, old, new, kwargs):
        self.log("Retrain triggered via input_button")
        self._retrain_all()

    def _on_retrain_event(self, event_name, data, kwargs):
        self.log("Retrain triggered via event")
        self._retrain_all()

    def _retrain_all(self):
        for room, cfg in ROOMS.items():
            try:
                new_models, meta = self._train_for_room(room, cfg)
                if new_models:
                    self.models[room] = new_models
                    self.train_meta[room] = meta
                    self.log(f"Retrained {room}: {meta}")
            except Exception as e:
                self.log(f"Training failed for {room}: {e}", level="ERROR")
