"""
BedSidePredictor AppDaemon App
----------------------------------
Learns per-side (east/west) bed occupancy probability curves using
the user's button-driven input_booleans as truth labels.

Key choices:
- Uses HA recorder history for 0/1 numeric mirrors you created
  (sensor.east_bed_occupied_num, sensor.west_bed_occupied_num).
- Masks out periods when person.ryan != 'home' or guest_mode == 'on'.
- Applies a minimum dwell filter to remove accidental taps.
- Requires minimum sample counts for both classes before training.
- Fits regularized logistic regression with class_weight='balanced'.
- Publishes current probability sensors and attaches a 24h curve
  (96 points, 15-minute resolution) in attributes for graphing.

This app does NOT duplicate raw load-cell filtering from bed_occupancy.py:
- bed_occupancy.py remains your authoritative global bed detector.
- This app only models per-side patterns from your side booleans.

Dependencies:
    numpy, pandas, scikit-learn, scipy

Publish:
    sensor.chatgpt_prob_east_bed_occupied
    sensor.chatgpt_prob_west_bed_occupied

Author: Ryan Claussen + ChatGPT (GPT-5 Thinking)
"""

import appdaemon.plugins.hass.hassapi as hass
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
import json
import math

class BedSidePredictor(hass.Hass):
    # -------------------------- Initialization -------------------------- #
    def initialize(self):
        """
        Initialize AppDaemon app and schedule training/updates.
        """
        # Args
        self.east_sensor = self.args.get("east_sensor", "sensor.east_bed_occupied_num")
        self.west_sensor = self.args.get("west_sensor", "sensor.west_bed_occupied_num")
        self.presence_sensor = self.args.get("presence_sensor", "person.ryan")
        self.guest_mode = self.args.get("guest_mode", "input_boolean.guest_mode")

        # Schedule config
        self.train_hour = int(self.args.get("train_hour", 16))  # local hour for main daily training
        self.update_every_minutes = int(self.args.get("update_every_minutes", 60))  # refresh probability

        # Data window and filters
        self.lookback_days = int(self.args.get("lookback_days", 56))
        self.min_dwell_minutes = int(self.args.get("min_dwell_minutes", 5))
        self.min_positive_minutes = int(self.args.get("min_positive_minutes", 300))  # ~5 hours across window
        self.min_negative_minutes = int(self.args.get("min_negative_minutes", 600))  # ensure enough 0s
        self.timezone = self.args.get("timezone", "America/Chicago")
        self.debug = bool(self.args.get("debug", False))

        self.log("BedSidePredictor initializing...", ascii_encode=False)
        self._log_cfg()

        # Schedule main daily training at train_hour
        run_time = datetime.now().replace(hour=self.train_hour, minute=0, second=1, microsecond=0)
        if run_time < datetime.now():
            run_time += timedelta(days=1)
        self.run_every(self.train_model_callback, run_time, 24 * 3600)

        # Light periodic updates to keep "current probability" fresh
        self.run_every(self.update_probabilities_only, datetime.now() + timedelta(minutes=1), self.update_every_minutes * 60)

        # Run a first training shortly after startup
        self.run_in(self.train_model_callback, 5)

        # Internal models cache
        self.models: Dict[str, Optional[LogisticRegression]] = {"east": None, "west": None}
        self.train_meta: Dict[str, Dict] = {"east": {}, "west": {}}

    # -------------------------- Utilities -------------------------- #
    def log_debug(self, msg: str):
        if self.debug:
            self.log(f"[DEBUG] {msg}", ascii_encode=False)

    def _log_cfg(self):
        self.log_debug(
            f"Config -> lookback_days={self.lookback_days}, min_dwell_minutes={self.min_dwell_minutes}, "
            f"min_pos={self.min_positive_minutes}, min_neg={self.min_negative_minutes}, tz={self.timezone}"
        )

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    # -------------------------- History helpers -------------------------- #
    def _fetch_binary_series(self, entity_id: str, days: int) -> pd.DataFrame:
        """
        Fetch state history for a 0/1 numeric sensor (or boolean mirrored as 0/1).
        Returns a DataFrame of state change points with tz-aware UTC timestamps.
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        hist = self.get_history(entity_id=entity_id, start_time=start_time, end_time=end_time)

        if not hist or len(hist[0]) == 0:
            self.log_debug(f"No history for {entity_id}")
            return pd.DataFrame(columns=["ts", "value"])

        records = []
        for r in hist[0]:
            s = r.get("state")
            if s in ("unknown", "unavailable", None, ""):
                continue
            try:
                v = float(s)
            except Exception:
                # handle 'on'/'off' just in case
                if s == "on":
                    v = 1.0
                elif s == "off":
                    v = 0.0
                else:
                    continue
            ts = r.get("last_changed")
            if ts is None:
                continue
            records.append({"ts": pd.to_datetime(ts), "value": v})

        df = pd.DataFrame.from_records(records)
        if df.empty:
            return df
        # Ensure tz-aware UTC
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")
        return df.sort_values("ts").reset_index(drop=True)

    def _fetch_presence_series(self, days: int) -> pd.DataFrame:
        """
        Fetch presence sensor ('home', 'away', etc.) as a 0/1 numeric series (home=1, else=0).
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        hist = self.get_history(entity_id=self.presence_sensor, start_time=start_time, end_time=end_time)

        if not hist or len(hist[0]) == 0:
            self.log_debug(f"No history for presence {self.presence_sensor}")
            return pd.DataFrame(columns=["ts", "home"])

        recs = []
        for r in hist[0]:
            state = r.get("state")
            ts = r.get("last_changed")
            if state in ("unknown", "unavailable", None, "") or ts is None:
                continue
            recs.append({"ts": pd.to_datetime(ts), "home": 1.0 if state == "home" else 0.0})

        df = pd.DataFrame.from_records(recs)
        if df.empty:
            return df
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")
        return df.sort_values("ts").reset_index(drop=True)

    def _fetch_guest_series(self, days: int) -> pd.DataFrame:
        """
        Fetch guest_mode boolean and map on=1, off=0.
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        hist = self.get_history(entity_id=self.guest_mode, start_time=start_time, end_time=end_time)

        if not hist or len(hist[0]) == 0:
            self.log_debug(f"No history for guest_mode {self.guest_mode}")
            return pd.DataFrame(columns=["ts", "guest"])

        recs = []
        for r in hist[0]:
            s = r.get("state")
            ts = r.get("last_changed")
            if s in ("unknown", "unavailable", None, "") or ts is None:
                continue
            v = 1.0 if s == "on" else 0.0
            recs.append({"ts": pd.to_datetime(ts), "guest": v})

        df = pd.DataFrame.from_records(recs)
        if df.empty:
            return df
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")
        return df.sort_values("ts").reset_index(drop=True)

    # -------------------------- Resampling & filtering -------------------------- #
    def _resample_minutely(self, df: pd.DataFrame, col: str, start_utc: datetime, end_utc: datetime) -> pd.Series:
        """
        Resample change-point history into a 1-minute regular series with forward-fill.
        """
        if df.empty:
            return pd.Series(dtype=float)

        # Build a full minute index
        idx = pd.date_range(start=start_utc, end=end_utc, freq="1min", tz="UTC")

        # Ensure the first value exists at start by prepending last-known state if needed
        # Forward-fill from earliest known value
        df2 = df.copy()
        df2 = df2.set_index("ts").sort_index()
        # Reindex on the minute grid and ffill
        s = df2[col].reindex(df2.index.union(idx)).sort_index().ffill().reindex(idx)
        return s.astype(float)

    def _apply_min_dwell(self, s: pd.Series, min_minutes: int) -> pd.Series:
        """
        Remove short state bursts shorter than min_minutes.
        This is a simple run-length filter on a binary series.
        """
        if s.empty:
            return s

        arr = s.values.astype(int)
        n = len(arr)
        if n == 0:
            return s

        # Identify runs
        changes = np.diff(arr, prepend=arr[0])
        # positions where value changes
        change_idx = np.where(changes != 0)[0]
        # start positions of runs
        run_starts = np.concatenate(([0], change_idx))
        # end positions (exclusive)
        run_ends = np.concatenate((change_idx, [n]))
        run_vals = arr[run_starts]

        # enforce minimum length
        min_len = max(1, min_minutes)  # minutes since 1 step = 1 minute
        for rs, re, v in zip(run_starts, run_ends, run_vals):
            length = re - rs
            if length < min_len:
                # Flip short blip to the surrounding majority (previous value if exists, else next)
                prev_val = arr[rs - 1] if rs > 0 else arr[re] if re < n else 0
                arr[rs:re] = prev_val

        return pd.Series(arr, index=s.index, dtype=float)

    def _mask_training(self, y: pd.Series, home: Optional[pd.Series], guest: Optional[pd.Series]) -> pd.Series:
        """
        Mask labels where user is away (home=0) or guest_mode=on (guest=1).
        """
        mask = pd.Series(True, index=y.index)
        if home is not None and not home.empty:
            mask = mask & (home.reindex(y.index).fillna(method="ffill").fillna(0.0) > 0.5)
        if guest is not None and not guest.empty:
            mask = mask & (guest.reindex(y.index).fillna(method="ffill").fillna(0.0) < 0.5)
        return y.where(mask)

    # -------------------------- Feature engineering -------------------------- #
    def _features_from_index(self, idx_utc: pd.DatetimeIndex) -> pd.DataFrame:
        """
        Build cyclic time features from a UTC index, using local timezone for hour/weekday.
        """
        idx_local = idx_utc.tz_convert(self.timezone)
        hour = idx_local.hour + idx_local.minute / 60.0
        weekday = idx_local.weekday
        features = pd.DataFrame(
            {
                "hour_sin": np.sin(2 * np.pi * hour / 24.0),
                "hour_cos": np.cos(2 * np.pi * hour / 24.0),
                "weekday_sin": np.sin(2 * np.pi * weekday / 7.0),
                "weekday_cos": np.cos(2 * np.pi * weekday / 7.0),
            },
            index=idx_utc,
        )
        return features

    # -------------------------- Training -------------------------- #
    def _train_for_side(self, side: str, entity_id: str) -> Tuple[Optional[LogisticRegression], Dict]:
        """
        Train model for a single side. Returns (model, metadata).
        """
        end_utc = self._utcnow()
        start_utc = end_utc - timedelta(days=self.lookback_days)

        # Fetch series
        y_df = self._fetch_binary_series(entity_id, self.lookback_days)
        if y_df.empty:
            self.log_debug(f"No data available for {entity_id}.")
            return None, {"reason": "no_history"}

        home_df = self._fetch_presence_series(self.lookback_days)
        guest_df = self._fetch_guest_series(self.lookback_days)

        # Resample to minutely
        y = self._resample_minutely(y_df, "value", start_utc, end_utc)
        if y.empty:
            return None, {"reason": "no_minutely_series"}

        # Dwell filtering to remove accidental taps
        y = self._apply_min_dwell(y, self.min_dwell_minutes)

        # Mask away/guest
        home = self._resample_minutely(home_df, "home", start_utc, end_utc) if not home_df.empty else None
        guest = self._resample_minutely(guest_df, "guest", start_utc, end_utc) if not guest_df.empty else None
        y_masked = self._mask_training(y, home, guest)

        # Drop masked minutes
        valid = y_masked.dropna()
        if valid.empty:
            return None, {"reason": "all_masked"}

        # Minimum class counts
        pos = int((valid > 0.5).sum())
        neg = int((valid <= 0.5).sum())

        if pos < self.min_positive_minutes or neg < self.min_negative_minutes:
            return None, {
                "reason": "insufficient_class_counts",
                "pos_minutes": pos,
                "neg_minutes": neg,
                "required_pos": self.min_positive_minutes,
                "required_neg": self.min_negative_minutes,
            }

        # Features
        X = self._features_from_index(valid.index)
        y_vec = (valid.values > 0.5).astype(int)

        # Fit logistic regression
        model = LogisticRegression(
            max_iter=500,
            class_weight="balanced",
            solver="lbfgs",
            n_jobs=None,
        )
        model.fit(X.values, y_vec)

        # Quick holdout AUC: use last 7 days as pseudo-holdout if available
        cutoff = valid.index.max() - pd.Timedelta(days=min(7, self.lookback_days // 4))
        train_idx = valid.index <= cutoff
        test_idx = valid.index > cutoff
        auc = None
        try:
            if train_idx.any() and test_idx.any():
                model_holdout = LogisticRegression(
                    max_iter=500,
                    class_weight="balanced",
                    solver="lbfgs",
                    n_jobs=None,
                ).fit(X.values[train_idx], y_vec[train_idx])
                y_proba = model_holdout.predict_proba(X.values[test_idx])[:, 1]
                auc = float(roc_auc_score(y_vec[test_idx], y_proba))
        except Exception as e:
            self.log_debug(f"{side} AUC computation failed: {repr(e)}")

        meta = {
            "trained_at": datetime.now().isoformat(),
            "window_days": self.lookback_days,
            "min_dwell_minutes": self.min_dwell_minutes,
            "samples_used": int(valid.shape[0]),
            "pos_minutes": pos,
            "neg_minutes": neg,
            "class_balance": round(pos / max(1, pos + neg), 4),
            "auc_last_week": auc,
            "masked_away": home is not None,
            "masked_guest": guest is not None,
        }
        return model, meta

    # -------------------------- Prediction & publishing -------------------------- #
    def _predict_curve(self, model: LogisticRegression, base_time_local: Optional[datetime] = None) -> pd.DataFrame:
        """
        Predict 24h curve at 15-minute steps using today's weekday.
        Returns DataFrame with columns [ts_local, hour, probability].
        """
        if base_time_local is None:
            base_time_local = datetime.now()

        # Build next 24h at 15-minute resolution in LOCAL time
        steps = 96
        start_local = base_time_local.replace(second=0, microsecond=0)
        times_local = [start_local + timedelta(minutes=15 * i) for i in range(steps)]

        # Convert to UTC index aligned to our feature function
        idx_local = pd.DatetimeIndex(times_local).tz_localize(self.timezone)
        idx_utc = idx_local.tz_convert("UTC")

        X = self._features_from_index(idx_utc).values
        proba = model.predict_proba(X)[:, 1]

        df = pd.DataFrame(
            {
                "ts_local": times_local,
                "hour": [t.hour + t.minute / 60.0 for t in times_local],
                "probability": proba,
            }
        )
        return df

    def _publish_current_prob(self, side: str, current_prob: float, attrs: Dict):
        """
        Publish a single sensor with attributes.
        """
        entity = f"sensor.chatgpt_prob_{side}_bed_occupied"
        attributes = {
            "friendly_name": f"{side.title()} Bed Occupied Probability",
            "unit_of_measurement": "%",
        }
        attributes.update(attrs)

        self.set_state(entity, state=round(current_prob * 100.0, 1), attributes=attributes)
        self.log_debug(f"Published {entity} = {round(current_prob * 100.0, 1)}%")

    # -------------------------- Callbacks -------------------------- #
    def train_model_callback(self, kwargs):
        """
        Full training pass for both sides, with filtering/masking and metrics.
        """
        self.log("Starting BedSidePredictor training run...", ascii_encode=False)

        for side, entity_id in {"east": self.east_sensor, "west": self.west_sensor}.items():
            try:
                model, meta = self._train_for_side(side, entity_id)
                self.train_meta[side] = meta

                if model is None:
                    reason = meta.get("reason", "unknown")
                    self.log_debug(f"{side.title()} side: training skipped ({reason}). Meta={meta}")
                    # If we have an old model, keep using it for publishing
                    if self.models.get(side) is None:
                        continue
                else:
                    self.models[side] = model
                    self.log(f"{side.title()} side model updated. Samples={meta.get('samples_used')} AUC={meta.get('auc_last_week')}", ascii_encode=False)

                # Predict and publish current probability
                model_use = self.models.get(side)
                if model_use is None:
                    continue
                curve = self._predict_curve(model_use)
                now_local = datetime.now()
                now_hour = now_local.hour + now_local.minute / 60.0
                idx = int(np.argmin(np.abs(curve["hour"].values - now_hour)))
                current_prob = float(curve.loc[idx, "probability"])

                # Attach compact curve to attributes for easy graphs
                attrs = {
                    "trained_at": meta.get("trained_at"),
                    "window_days": meta.get("window_days"),
                    "min_dwell_minutes": meta.get("min_dwell_minutes"),
                    "samples_used": meta.get("samples_used"),
                    "pos_minutes": meta.get("pos_minutes"),
                    "neg_minutes": meta.get("neg_minutes"),
                    "class_balance": meta.get("class_balance"),
                    "auc_last_week": meta.get("auc_last_week"),
                    "curve_hours": [float(h) for h in curve["hour"].round(3).tolist()],
                    "curve_probs": [float(p) for p in np.round(curve["probability"].astype(float), 4).tolist()],
                }
                self._publish_current_prob(side, current_prob, attrs)

            except Exception as e:
                self.log(f"Error processing {side} side: {e}", level="ERROR", ascii_encode=False)
                self.log_debug(f"Traceback: {repr(e)}")

        self.log("BedSidePredictor training complete.", ascii_encode=False)

    def update_probabilities_only(self, kwargs):
        """
        Periodic lightweight update: reuse the last trained models to publish fresh "current probability"
        without re-training. If models don't exist yet, no-op.
        """
        for side in ("east", "west"):
            model = self.models.get(side)
            meta = self.train_meta.get(side, {})
            if model is None:
                continue
            try:
                curve = self._predict_curve(model)
                now_local = datetime.now()
                now_hour = now_local.hour + now_local.minute / 60.0
                idx = int(np.argmin(np.abs(curve["hour"].values - now_hour)))
                current_prob = float(curve.loc[idx, "probability"])

                attrs = {
                    "trained_at": meta.get("trained_at"),
                    "window_days": meta.get("window_days"),
                    "min_dwell_minutes": meta.get("min_dwell_minutes"),
                    "samples_used": meta.get("samples_used"),
                    "pos_minutes": meta.get("pos_minutes"),
                    "neg_minutes": meta.get("neg_minutes"),
                    "class_balance": meta.get("class_balance"),
                    "auc_last_week": meta.get("auc_last_week"),
                    "curve_hours": [float(h) for h in curve["hour"].round(3).tolist()],
                    "curve_probs": [float(p) for p in np.round(curve["probability"].astype(float), 4).tolist()],
                }
                self._publish_current_prob(side, current_prob, attrs)
            except Exception as e:
                self.log(f"Error updating probabilities for {side}: {e}", level="ERROR", ascii_encode=False)
                self.log_debug(f"Traceback: {repr(e)}")
