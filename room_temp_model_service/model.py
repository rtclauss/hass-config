"""Pure-Python room-temperature model core (no Home Assistant / AppDaemon deps).

Owns everything CPU/memory heavy so it can run in a standalone container off
the Home Assistant host:

  * training  — pulls multi-year history from InfluxDB v1, engineers features
                (astral sun position, cyclic time, oracle forecast proxies),
                fits a GradientBoostingRegressor per room per horizon with
                purged interleaved-week CV, and saves joblib models + metadata.
  * inference — given a raw feature payload (current sensor values + a short
                weather forecast) it assembles the same feature vector and
                returns T+15/30/60 predictions.

Feature engineering is defined once here, so training and inference cannot
drift. The service layer (service.py) handles all MQTT / transport concerns.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

HORIZONS = [15, 30, 60]
SLOT_MIN = 5
HORIZON_SLOTS = {h: h // SLOT_MIN for h in HORIZONS}
PURGE_SLOTS = 48  # 4-hour autocorrelation purge at fold boundaries
MIN_COVERAGE = 0.5  # drop candidate features with < this fraction of history


def sun_position(lat, lon, dt):
    """(elevation_deg, azimuth_deg) for a UTC datetime, via astral or fallback."""
    try:
        from astral import LocationInfo
        from astral.sun import azimuth as astral_azimuth
        from astral.sun import elevation as astral_elevation
        loc = LocationInfo(latitude=lat, longitude=lon)
        return float(astral_elevation(loc.observer, dt)), float(astral_azimuth(loc.observer, dt))
    except Exception:
        pass
    # Pure-math fallback (good to ~1°).
    lat_r = math.radians(lat)
    doy = dt.timetuple().tm_yday
    hour_utc = dt.hour + dt.minute / 60.0
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (doy - 81))))
    hour_angle = math.radians(15 * (hour_utc + lon / 15 - 12))
    sin_elev = (math.sin(lat_r) * math.sin(decl)
                + math.cos(lat_r) * math.cos(decl) * math.cos(hour_angle))
    elev = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))
    cos_az = (math.sin(decl) - math.sin(math.radians(elev)) * math.sin(lat_r)) / (
        math.cos(math.radians(elev)) * math.cos(lat_r) + 1e-9
    )
    azim = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    if math.sin(hour_angle) > 0:
        azim = 360 - azim
    return elev, azim


class RoomTempModel:
    def __init__(self, config):
        """config: dict with model_dir, latitude, longitude, min_training_samples,
        influxdb {host, port, database}, and rooms [{name, temp_sensors,
        humidity_sensor, confidence_sensor}]."""
        self.model_dir = config.get("model_dir", "/models")
        self.lat = float(config.get("latitude", 0.0))
        self.lon = float(config.get("longitude", 0.0))
        self.min_samples = int(config.get("min_training_samples", 500))
        influx = config.get("influxdb", {})
        self.influx_host = influx.get("host", "localhost")
        self.influx_port = int(influx.get("port", 8086))
        self.influx_db = influx.get("database", "home_assistant")
        self.rooms = {r["name"]: r for r in config.get("rooms", [])}

        self.models = {room: {} for room in self.rooms}
        self.meta = {room: {} for room in self.rooms}
        os.makedirs(self.model_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _model_path(self, room, horizon):
        return os.path.join(self.model_dir, f"room_temp_{room}_{horizon}m.joblib")

    def _meta_path(self, room):
        return os.path.join(self.model_dir, f"room_temp_{room}_meta.json")

    def load(self):
        # joblib.load deserializes pickle — safe here because these files are
        # produced only by this service's own train() into its own model_dir
        # volume (trusted, self-generated). Do not point model_dir at an
        # untrusted/shared location.
        import joblib
        for room in self.rooms:
            loaded = {}
            for h in HORIZONS:
                path = self._model_path(room, h)
                if os.path.exists(path):
                    try:
                        loaded[h] = joblib.load(path)
                    except Exception:
                        pass
            if loaded:
                self.models[room] = loaded
                if os.path.exists(self._meta_path(room)):
                    with open(self._meta_path(room)) as f:
                        self.meta[room] = json.load(f)

    # ------------------------------------------------------------------
    # InfluxDB helpers (training only)
    # ------------------------------------------------------------------

    def _influx_client(self):
        from influxdb import InfluxDBClient
        return InfluxDBClient(host=self.influx_host, port=self.influx_port, database=self.influx_db)

    @staticmethod
    def _influx_where(entity_id):
        """Build the WHERE clause for a fully-qualified Home Assistant entity_id.

        HA's InfluxDB integration does NOT store the fully-qualified entity_id:
        it tags each point with the bare object_id plus a separate `domain` tag.
        Querying entity_id='sensor.outside_temperature' matches nothing. The
        domain filter matters because the same object_id can exist in more than
        one domain (this database has both `sensor` and `number`).
        """
        if "." in entity_id:
            domain, object_id = entity_id.split(".", 1)
            return f"entity_id='{object_id}' AND domain='{domain}'"
        return f"entity_id='{entity_id}'"

    def _query_generic(self, client, entity_id, start_days=730):
        import pandas as pd
        start = (datetime.now(timezone.utc) - timedelta(days=start_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = (f"SELECT value FROM /.*/ WHERE {self._influx_where(entity_id)} "
             f"AND time>='{start}' ORDER BY time ASC")
        try:
            result = client.query(q)
            pts = []
            for _k, points in result.items():
                pts.extend(list(points))
            if not pts:
                return None
            df = pd.DataFrame(pts)
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time").sort_index()
            if "value" not in df.columns:
                return None
            return df["value"].astype(float).resample(f"{SLOT_MIN}min").mean().ffill(limit=12)
        except Exception:
            return None

    def _query_categorical(self, client, entity_id, start_days=730):
        """Read a string-valued sensor (e.g. sensor.hvac_activity).

        Home Assistant writes non-numeric states differently from numeric ones:
        the field is `state` (not `value`) and the measurement is the
        fully-qualified entity_id rather than the unit. Selecting `value` here
        returns nothing, which silently turns the HVAC one-hots into constant
        zeros — and because they are 0.0 rather than NaN, the coverage filter
        keeps them. `value` is kept as a fallback for odd writers.
        """
        import pandas as pd
        start = (datetime.now(timezone.utc) - timedelta(days=start_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for field in ("state", "value"):
            q = (f"SELECT {field} FROM /.*/ WHERE {self._influx_where(entity_id)} "
                 f"AND time>='{start}' ORDER BY time ASC")
            try:
                result = client.query(q)
                pts = []
                for _k, points in result.items():
                    pts.extend(list(points))
                if not pts:
                    continue
                df = pd.DataFrame(pts)
                if field not in df.columns:
                    continue
                df["time"] = pd.to_datetime(df["time"])
                df = df.set_index("time").sort_index()
                series = df[field].dropna()
                if series.empty:
                    continue
                return series.astype(str).resample(f"{SLOT_MIN}min").ffill()
            except Exception:
                continue
        return pd.Series(dtype=object)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _build_training_data(self, room, cfg):
        import numpy as np
        import pandas as pd

        client = self._influx_client()

        members = [self._query_generic(client, s) for s in cfg["temp_sensors"]]
        members = [m for m in members if m is not None and not m.empty]
        if not members:
            return None, None
        room_temp = pd.concat(members, axis=1).mean(axis=1).dropna()
        if len(room_temp) < self.min_samples:
            return None, None

        # NB: never write `query(...) or pd.Series(...)` — bool() on a non-empty
        # Series raises "truth value is ambiguous", which the caller's except
        # would swallow into a silent training failure.
        def q(entity_id):
            s = self._query_generic(client, entity_id) if entity_id else None
            return s if s is not None else pd.Series(dtype=float)

        outside_temp = q("sensor.outside_temperature")
        outside_humidity = q("sensor.outside_humidity")
        cloud_cover = q("sensor.tomorrow_io_the_brewery_cloud_cover")
        wind_speed = q("sensor.pinehotties_wind_speed")
        precipitation = q("sensor.pinehotties_hourly_rain")
        uv_index = q("sensor.pinehotties_uv_index")
        hvac_series = self._query_categorical(client, "sensor.hvac_activity")

        hum_sensors = cfg.get("humidity_sensors")
        if not hum_sensors:
            hum_sensors = [cfg["humidity_sensor"]] if cfg.get("humidity_sensor") else []
        hum_members = [self._query_generic(client, s) for s in hum_sensors]
        hum_members = [m for m in hum_members if m is not None and not m.empty]
        room_humidity = (pd.concat(hum_members, axis=1).mean(axis=1)
                         if hum_members else pd.Series(dtype=float))

        confidence = q(cfg.get("confidence_sensor"))

        idx = room_temp.index

        def align(s):
            # An empty series carries a RangeIndex; reindexing that onto a
            # DatetimeIndex with method="nearest" raises. A sensor with no
            # history must become an all-NaN column so the coverage filter
            # below can drop it.
            if s is None or len(s) == 0:
                return pd.Series(float("nan"), index=idx)
            return s.reindex(idx, method="nearest", tolerance=pd.Timedelta("10min"))

        df = pd.DataFrame({"room_temp": room_temp}, index=idx)
        df["room_humidity"] = align(room_humidity)
        df["outside_temp"] = align(outside_temp)
        df["outside_humidity"] = align(outside_humidity)
        df["cloud_cover"] = align(cloud_cover)
        df["wind_speed"] = align(wind_speed)
        df["precipitation"] = align(precipitation)
        df["uv_index"] = align(uv_index)
        df["occupancy"] = align(confidence).fillna(0)

        # Junk 0 filter on outside temp/humidity (humidity never legit 0 here).
        junk = df["outside_humidity"] <= 0
        df.loc[junk, ["outside_temp", "outside_humidity"]] = np.nan
        df["outside_temp"] = df["outside_temp"].ffill(limit=12)
        df["outside_humidity"] = df["outside_humidity"].ffill(limit=12)

        if not hvac_series.empty:
            hvac_str = align(hvac_series)
        else:
            hvac_str = pd.Series(index=idx, dtype=object)
        df["hvac_heating"] = (hvac_str == "heating").astype(float)
        df["hvac_cooling"] = (hvac_str == "cooling").astype(float)

        # polyfit returns slope per sample step and the series is resampled at
        # SLOT_MIN, so divide to get °F/min — the unit the live predictor
        # publishes and the linear fallback assumes (room_temp + rate * horizon).
        df["room_temp_rate_15m"] = (
            df["room_temp"].rolling(3, min_periods=2)
            .apply(lambda x: np.polyfit(range(len(x)), x, 1)[0] if len(x) >= 2 else 0, raw=True)
        ) / SLOT_MIN
        df["outside_delta_3h"] = df["outside_temp"].diff(36)

        hours = df.index.hour + df.index.minute / 60.0
        doy = df.index.dayofyear
        df["hour_sin"] = np.sin(2 * np.pi * hours / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hours / 24)
        df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
        df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

        # Sun position is the expensive per-row computation. The horizon-shifted
        # times (t+15/30/60) land on the same 5-min grid as the base times, so a
        # local memo turns ~4 astral calls per row into ~1 (most horizon lookups
        # hit a base-time entry). Keyed by the UTC datetime.
        _sun_cache = {}

        def _sun(dt):
            v = _sun_cache.get(dt)
            if v is None:
                v = sun_position(self.lat, self.lon, dt)
                _sun_cache[dt] = v
            return v

        base_dts = [ts.to_pydatetime().replace(tzinfo=timezone.utc) for ts in df.index]
        sun_vals = [_sun(dt) for dt in base_dts]
        df["sun_elevation"] = [v[0] for v in sun_vals]
        df["sun_azimuth_sin"] = np.sin(np.radians([v[1] for v in sun_vals]))
        df["sun_azimuth_cos"] = np.cos(np.radians([v[1] for v in sun_vals]))

        for h, slots in HORIZON_SLOTS.items():
            df[f"cloud_cover_{h}m"] = df["cloud_cover"].shift(-slots)
            df[f"outside_temp_{h}m"] = df["outside_temp"].shift(-slots)
            df[f"outside_humidity_{h}m"] = df["outside_humidity"].shift(-slots)
            df[f"wind_speed_{h}m"] = df["wind_speed"].shift(-slots)
            df[f"precipitation_{h}m"] = df["precipitation"].shift(-slots)
            df[f"uv_index_{h}m"] = df["uv_index"].shift(-slots)
            delta = timedelta(minutes=h)
            sun_future = [_sun(dt + delta) for dt in base_dts]
            df[f"sun_elevation_{h}m"] = [v[0] for v in sun_future]
            df[f"sun_azimuth_sin_{h}m"] = np.sin(np.radians([v[1] for v in sun_future]))
            df[f"sun_azimuth_cos_{h}m"] = np.cos(np.radians([v[1] for v in sun_future]))

        y_dict = {}
        for h, slots in HORIZON_SLOTS.items():
            y_dict[f"delta_{h}"] = df["room_temp"].shift(-slots) - df["room_temp"]

        # Coverage filter — drop candidate features without enough history so a
        # sparse new sensor can't collapse the set; survivors define feature_cols.
        feature_like = [c for c in df.columns if not c.startswith("delta_")]
        dropped = [c for c in feature_like if df[c].notna().mean() < MIN_COVERAGE]
        if dropped:
            df = df.drop(columns=dropped)

        df["fold"] = df.index.isocalendar().week % 5
        df = df.dropna()
        if len(df) < self.min_samples:
            return None, None
        return df, y_dict

    def train(self, rooms=None):
        """Train models for the given rooms (all by default). Returns a report."""
        import joblib
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.metrics import mean_squared_error

        report = {}
        for room in (rooms or list(self.rooms)):
            cfg = self.rooms.get(room)
            if not cfg:
                continue
            df, y_dict = self._build_training_data(room, cfg)
            if df is None:
                report[room] = {"status": "insufficient_data"}
                continue
            feature_cols = [c for c in df.columns if c != "fold" and not c.startswith("delta_")]
            X_all = df[feature_cols].to_numpy()

            # Purged interleaved-week folds. The fold split does not depend on
            # the horizon, so compute the (train, test) index masks once. The
            # purge zone is built with vectorized numpy slice-fills — O(n) — not
            # the old membership test against a numpy array, which was O(n^2)
            # and would not finish on multi-year data.
            n = len(df)
            fold_arr = df["fold"].to_numpy()
            fold_masks = []
            for fold_k in range(5):
                test = fold_arr == fold_k
                if test.sum() < 10:
                    fold_masks.append(None)
                    continue
                purged = np.zeros(n, dtype=bool)
                for i in np.flatnonzero(test):
                    purged[max(0, i - PURGE_SLOTS):min(n, i + PURGE_SLOTS + 1)] = True
                train = (~purged) & (fold_arr != fold_k)
                fold_masks.append((train, test) if train.sum() >= 100 else None)

            room_models, metrics = {}, {}
            for h in HORIZONS:
                y = y_dict[f"delta_{h}"].reindex(df.index).to_numpy()
                cv_rmses = []
                for masks in fold_masks:
                    if masks is None:
                        continue
                    train, test = masks
                    m = GradientBoostingRegressor(n_estimators=100, max_depth=4,
                                                  min_samples_leaf=20, random_state=42)
                    m.fit(X_all[train], y[train])
                    preds = m.predict(X_all[test])
                    cv_rmses.append(math.sqrt(mean_squared_error(y[test], preds)))
                cv_mean = round(float(np.mean(cv_rmses)), 3) if cv_rmses else None
                cv_std = round(float(np.std(cv_rmses)), 3) if cv_rmses else None
                final = GradientBoostingRegressor(n_estimators=100, max_depth=4,
                                                  min_samples_leaf=20, random_state=42)
                final.fit(X_all, y)
                joblib.dump(final, self._model_path(room, h))
                room_models[h] = final
                metrics[f"rmse_{h}m_cv_mean"] = cv_mean
                metrics[f"rmse_{h}m_cv_std"] = cv_std
            metrics["trained_at"] = datetime.now(timezone.utc).isoformat()
            metrics["n_samples"] = len(df)
            metrics["feature_cols"] = feature_cols
            with open(self._meta_path(room), "w") as f:
                json.dump(metrics, f)
            self.models[room] = room_models
            self.meta[room] = metrics
            report[room] = {"status": "trained", "n_samples": len(df),
                            "rmse_60m_cv_mean": metrics.get("rmse_60m_cv_mean")}
        return report

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _assemble_row(self, raw, ts):
        """Build the feature row from a raw payload + timestamp (adds sun/time)."""
        forecast = raw.get("forecast", {}) or {}
        hours = ts.hour + ts.minute / 60.0
        doy = ts.timetuple().tm_yday
        elev, azim = sun_position(self.lat, self.lon, ts)

        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        row = {
            "room_temp": num(raw.get("room_temp")),
            "room_humidity": num(raw.get("room_humidity")),
            "outside_temp": num(raw.get("outside_temp")),
            "outside_humidity": num(raw.get("outside_humidity")),
            "cloud_cover": num(raw.get("cloud_cover")),
            "wind_speed": num(raw.get("wind_speed")),
            "uv_index": num(raw.get("uv_index")),
            "precipitation": num(raw.get("precipitation")),
            "occupancy": num(raw.get("occupancy")) or 0,
            "hvac_heating": num(raw.get("hvac_heating")) or 0,
            "hvac_cooling": num(raw.get("hvac_cooling")) or 0,
            "room_temp_rate_15m": num(raw.get("room_temp_rate_15m")) or 0,
            "outside_delta_3h": num(raw.get("outside_delta_3h")) or 0,
            "hour_sin": math.sin(2 * math.pi * hours / 24),
            "hour_cos": math.cos(2 * math.pi * hours / 24),
            "doy_sin": math.sin(2 * math.pi * doy / 365.25),
            "doy_cos": math.cos(2 * math.pi * doy / 365.25),
            "sun_elevation": elev,
            "sun_azimuth_sin": math.sin(math.radians(azim)),
            "sun_azimuth_cos": math.cos(math.radians(azim)),
        }
        for h in HORIZONS:
            fc = forecast.get(str(h)) or forecast.get(h) or {}
            elev_f, azim_f = sun_position(self.lat, self.lon, ts + timedelta(minutes=h))
            row[f"cloud_cover_{h}m"] = num(fc.get("cloud_cover")) if fc.get("cloud_cover") is not None else row["cloud_cover"]
            row[f"outside_temp_{h}m"] = num(fc.get("temperature")) if fc.get("temperature") is not None else row["outside_temp"]
            row[f"outside_humidity_{h}m"] = num(fc.get("humidity")) if fc.get("humidity") is not None else row["outside_humidity"]
            row[f"wind_speed_{h}m"] = num(fc.get("wind_speed")) if fc.get("wind_speed") is not None else row["wind_speed"]
            row[f"precipitation_{h}m"] = num(fc.get("precipitation")) if fc.get("precipitation") is not None else row["precipitation"]
            row[f"uv_index_{h}m"] = num(fc.get("uv_index")) if fc.get("uv_index") is not None else row["uv_index"]
            row[f"sun_elevation_{h}m"] = elev_f
            row[f"sun_azimuth_sin_{h}m"] = math.sin(math.radians(azim_f))
            row[f"sun_azimuth_cos_{h}m"] = math.cos(math.radians(azim_f))
        return row

    def predict(self, room, raw, ts=None):
        """Return {t15,t30,t60,prediction_source, ...cv metrics}. `raw` is the
        feature payload from the AppDaemon shim; `ts` is a tz-aware UTC time."""
        ts = ts or datetime.now(timezone.utc)
        room_temp = raw.get("room_temp")
        try:
            room_temp = float(room_temp)
        except (TypeError, ValueError):
            return None

        models = self.models.get(room, {})
        meta = self.meta.get(room, {})
        result = {"prediction_source": None, "trained_at": meta.get("trained_at")}

        if not models:
            rate = 0.0
            try:
                rate = float(raw.get("room_temp_rate_15m") or 0.0)
            except (TypeError, ValueError):
                rate = 0.0
            for h in HORIZONS:
                result[f"t{h}"] = round(room_temp + rate * h, 2)
            result["prediction_source"] = "fallback_linear"
            return result

        row = self._assemble_row(raw, ts)
        feature_cols = meta.get("feature_cols")
        if feature_cols:
            import pandas as pd
            X = pd.DataFrame([row])[feature_cols].fillna(0)
            feat = X.values[0]
        else:
            feat = [row.get(k, 0) or 0 for k in sorted(row.keys())]
        for h in HORIZONS:
            result[f"t{h}"] = round(room_temp + float(models[h].predict([feat])[0]), 2)
        result["prediction_source"] = "gbr_model"
        for h in HORIZONS:
            result[f"rmse_{h}m_cv_mean"] = meta.get(f"rmse_{h}m_cv_mean")
        result["n_training_samples"] = meta.get("n_samples")
        return result
