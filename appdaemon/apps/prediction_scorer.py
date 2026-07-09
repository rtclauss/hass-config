"""Score room-temperature predictions against what actually happened.

room_temp_predictor publishes T+15/30/60 predictions but only reports
training-time CV RMSE. This app closes the loop: every 5 minutes it stamps the
current predictions, and once a horizon matures (e.g. the T+60 stamped 60 min
ago) it compares that prediction to the actual room temperature now.

It publishes live rolling accuracy (MAE / RMSE / signed bias per horizon per
room), writes each scored point to InfluxDB for Grafana trend dashboards, and
fires a retrain-nudge (event + notification) when live RMSE persistently
exceeds the model's training CV RMSE — a data-driven signal for when to press
input_button.retrain_room_temp_models.

State is persisted to disk so a restart doesn't lose the in-flight window
(AppDaemon instance vars reset on reload).
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import hassapi as hass

HORIZONS = [15, 30, 60]

ROOM_TEMP = {
    "owner_suite": "sensor.owner_suite_tph_temperature",
    "office": "sensor.office_tph_temperature",
    "guest_room": "sensor.guest_room_tph_temperature",
}


class PredictionScorer(hass.Hass):
    def initialize(self):
        self.model_dir = self.args.get("model_dir", "/config/appdaemon/models")
        self.window_days = int(self.args.get("window_days", 7))
        self.tol_min = float(self.args.get("match_tolerance_min", 2.5))
        self.min_samples = int(self.args.get("min_samples_for_nudge", 50))
        self.nudge_cooldown_h = float(self.args.get("nudge_cooldown_hours", 24))
        self.rmse_ratio_default = float(self.args.get("retrain_rmse_ratio", 2.0))
        self.ratio_helper = self.args.get(
            "retrain_ratio_helper", "input_number.prediction_retrain_rmse_ratio"
        )
        self.nudge_switch = self.args.get(
            "nudge_switch", "input_boolean.prediction_scorer_nudge_enabled"
        )
        self.notify_service = self.args.get("notify_service")  # optional, e.g. "notify/mobile_app_x"

        self.influxdb_host = self.args.get("influxdb_host", "localhost")
        self.influxdb_port = int(self.args.get("influxdb_port", 8086))
        self.influxdb_db = self.args.get("influxdb_database", "home_assistant")
        self.influx_measurement = self.args.get(
            "influx_measurement", "room_temp_prediction_error"
        )

        self.pending = []      # [{ts, room, preds:{'15','30','60'}, source, scored:[h,...]}]
        self.scored = []       # [{scored_ts, pred_ts, room, horizon, predicted, actual, error, source}]
        self.last_nudge = None
        os.makedirs(self.model_dir, exist_ok=True)
        self._load()

        start = datetime.now(timezone.utc) + timedelta(seconds=90)
        self.run_every(self._score, start, 300)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _state_path(self):
        return os.path.join(self.model_dir, "prediction_scores.json")

    def _load(self):
        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self.pending = data.get("pending", [])
            self.scored = data.get("scored", [])
            self.last_nudge = data.get("last_nudge")
            self.log(f"Loaded {len(self.scored)} scored / {len(self.pending)} pending records")
        except Exception as e:
            self.log(f"Failed to load scorer state: {e}", level="WARNING")

    def _save(self):
        try:
            with open(self._state_path(), "w") as f:
                json.dump(
                    {"pending": self.pending, "scored": self.scored, "last_nudge": self.last_nudge},
                    f,
                )
        except Exception as e:
            self.log(f"Failed to save scorer state: {e}", level="WARNING")

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

    @staticmethod
    def _parse(ts):
        return datetime.fromisoformat(ts)

    def _pred_attr(self, room, attr):
        return self._safe_float(
            self.get_state(f"sensor.room_temp_prediction_{room}", attribute=attr)
        )

    # ------------------------------------------------------------------
    # Scoring loop
    # ------------------------------------------------------------------

    def _score(self, kwargs):
        now = datetime.now(timezone.utc)

        # 1. Stamp the current predictions for each room.
        for room in ROOM_TEMP:
            preds = {str(h): self._pred_attr(room, f"t{h}") for h in HORIZONS}
            if all(v is None for v in preds.values()):
                continue
            self.pending.append({
                "ts": now.isoformat(),
                "room": room,
                "preds": preds,
                "source": self.get_state(
                    f"sensor.room_temp_prediction_{room}", attribute="prediction_source"
                ),
                "scored": [],
            })

        # 2. Mature & score any prediction whose horizon has just elapsed.
        new_points = []
        still_pending = []
        for rec in self.pending:
            age_min = (now - self._parse(rec["ts"])).total_seconds() / 60.0
            done_h = rec.setdefault("scored", [])
            for h in HORIZONS:
                if h in done_h:
                    continue
                if abs(age_min - h) <= self.tol_min:
                    actual = self._safe_float(self.get_state(ROOM_TEMP[rec["room"]]))
                    pred = self._safe_float(rec["preds"].get(str(h)))
                    if actual is not None and pred is not None:
                        sp = {
                            "scored_ts": now.isoformat(),
                            "pred_ts": rec["ts"],
                            "room": rec["room"],
                            "horizon": h,
                            "predicted": pred,
                            "actual": actual,
                            "error": round(actual - pred, 3),
                            "source": rec.get("source"),
                        }
                        self.scored.append(sp)
                        new_points.append(sp)
                    done_h.append(h)
                elif age_min > h + self.tol_min:
                    done_h.append(h)  # missed the match window (app was down) — give up
            if len(done_h) < len(HORIZONS) and age_min <= max(HORIZONS) + self.tol_min:
                still_pending.append(rec)
        self.pending = still_pending

        # 3. Prune scored history to the rolling window.
        cutoff = now - timedelta(days=self.window_days)
        self.scored = [s for s in self.scored if self._parse(s["scored_ts"]) >= cutoff]

        # 4. Persist to InfluxDB (Grafana), publish sensors, maybe nudge, save.
        self._influx_write(new_points)
        self._publish_metrics()
        self._maybe_nudge(now)
        self._save()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _room_metrics(self, room):
        """Return {horizon: {mae, rmse, bias, n}} for a room over the window."""
        out = {}
        for h in HORIZONS:
            errs = [s["error"] for s in self.scored if s["room"] == room and s["horizon"] == h]
            if not errs:
                out[h] = {"mae": None, "rmse": None, "bias": None, "n": 0}
                continue
            n = len(errs)
            out[h] = {
                "mae": round(sum(abs(e) for e in errs) / n, 3),
                "rmse": round(math.sqrt(sum(e * e for e in errs) / n), 3),
                "bias": round(sum(errs) / n, 3),
                "n": n,
            }
        return out

    def _publish_metrics(self):
        worst_rmse = None
        worst_where = None
        for room in ROOM_TEMP:
            m = self._room_metrics(room)
            rmse60 = m[60]["rmse"]
            attrs = {"window_days": self.window_days,
                     "prediction_source": self.get_state(
                         f"sensor.room_temp_prediction_{room}", attribute="prediction_source")}
            for h in HORIZONS:
                attrs[f"mae_{h}m"] = m[h]["mae"]
                attrs[f"rmse_{h}m"] = m[h]["rmse"]
                attrs[f"bias_{h}m"] = m[h]["bias"]
                attrs[f"n_{h}m"] = m[h]["n"]
            attrs["friendly_name"] = f"Prediction Error {room.replace('_', ' ').title()}"
            attrs["unit_of_measurement"] = "°F"
            self.set_state(
                f"sensor.room_temp_prediction_error_{room}",
                state=rmse60 if rmse60 is not None else "no_data",
                attributes=attrs,
            )
            for h in HORIZONS:
                r = m[h]["rmse"]
                if r is not None and (worst_rmse is None or r > worst_rmse):
                    worst_rmse = r
                    worst_where = f"{room}/t{h}"

        self.set_state(
            "sensor.room_temp_model_health",
            state=worst_rmse if worst_rmse is not None else "no_data",
            attributes={
                "worst": worst_where,
                "window_days": self.window_days,
                "unit_of_measurement": "°F",
                "friendly_name": "Room Temp Model Health (worst RMSE)",
            },
        )

    # ------------------------------------------------------------------
    # InfluxDB
    # ------------------------------------------------------------------

    def _influx_write(self, points):
        if not points:
            return
        try:
            from influxdb import InfluxDBClient
            client = InfluxDBClient(
                host=self.influxdb_host, port=self.influxdb_port, database=self.influxdb_db
            )
            client.write_points([
                {
                    "measurement": self.influx_measurement,
                    "tags": {
                        "room": p["room"],
                        "horizon": str(p["horizon"]),
                        "source": p.get("source") or "unknown",
                    },
                    "time": p["scored_ts"],
                    "fields": {
                        "error": float(p["error"]),
                        "abs_error": abs(float(p["error"])),
                        "predicted": float(p["predicted"]),
                        "actual": float(p["actual"]),
                    },
                }
                for p in points
            ])
        except Exception as e:
            self.log(f"InfluxDB write failed: {e}", level="WARNING")

    # ------------------------------------------------------------------
    # Retrain nudge
    # ------------------------------------------------------------------

    def _maybe_nudge(self, now):
        if self.get_state(self.nudge_switch) == "off":
            return
        ratio = self._safe_float(self.get_state(self.ratio_helper), self.rmse_ratio_default)

        offenders = []
        for room in ROOM_TEMP:
            m = self._room_metrics(room)
            live = m[60]["rmse"]
            n = m[60]["n"]
            cv = self._pred_attr(room, "rmse_60m_cv_mean")
            if live is None or cv is None or n < self.min_samples:
                continue
            if live > cv * ratio:
                offenders.append((room, live, cv, n))

        if not offenders:
            return
        if self.last_nudge:
            try:
                if (now - self._parse(self.last_nudge)).total_seconds() < self.nudge_cooldown_h * 3600:
                    return
            except Exception:
                pass

        detail = ", ".join(
            f"{r}: live RMSE {live:.2f}°F vs CV {cv:.2f}°F (n={n})"
            for r, live, cv, n in offenders
        )
        message = (
            f"Room-temp model drift detected over {self.window_days}d — {detail}. "
            f"Consider pressing input_button.retrain_room_temp_models."
        )
        self.fire_event(
            "room_temp_retrain_suggested",
            offenders=[
                {"room": r, "live_rmse_60m": live, "cv_rmse_60m": cv, "n": n}
                for r, live, cv, n in offenders
            ],
            ratio=ratio,
        )
        self.call_service(
            "persistent_notification/create",
            title="Room-temp model: retrain suggested",
            message=message,
            notification_id="room_temp_retrain_suggested",
        )
        if self.notify_service:
            try:
                domain, service = self.notify_service.split("/", 1)
                self.call_service(f"{domain}/{service}", message=message)
            except Exception as e:
                self.log(f"notify_service call failed: {e}", level="WARNING")

        self.last_nudge = now.isoformat()
        self.log(f"Retrain nudge fired: {detail}")
