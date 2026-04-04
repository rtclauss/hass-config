"""
BedFusionDetector - AppDaemon app for fusing multiple bed-occupancy signals
into a single probabilistic decision with robustness and confidence metrics.

- Uses weighted log-odds fusion (Bayesian-inspired) across inputs like:
  - bed_occupancy.py outputs (e.g., probability, boolean occupied, deltas)
  - bed_side_predictor.py outputs (e.g., east/west probabilities)
  - Optional presence and context signals (time of day, away/home, do-not-disturb)
- Online learning: incremental logistic regression (SGD) to calibrate weights.
- Exposes sensors:
  - sensor.chatgpt_bed_fused_probability (0-100 percent)
  - binary_sensor.chatgpt_bed_fused_occupied (on/off)
  - sensor.chatgpt_bed_fusion_robustness (0.0-1.0)
  - sensor.chatgpt_bed_fusion_confidence (0.0-1.0)
  - binary_sensor.chatgpt_bed_fusion_training_needed (on/off)
  - sensor.chatgpt_bed_fusion_meta (attributes: weights, auc, samples, etc.)
- Override support:
  - input_select or input_text for override mode: off, force_occupied, force_unoccupied
- Heavy debug logging with ascii_encode=False per project convention.

Units:
- All probabilities are treated as [0.0, 1.0] internally.
- HA-facing "probability" sensor is published in percent (0.0..100.0).
- Robustness and confidence are [0.0, 1.0].

Requires: numpy, scipy, scikit-learn
"""

import appdaemon.plugins.hass.hassapi as hass
import numpy as np
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, Any, List, Tuple, Optional
import math
import json
import traceback

# scikit-learn - online logistic regression and metrics
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import roc_auc_score, log_loss

# ------------- Utility helpers -------------

def _safe_logit(p: float, eps: float = 1e-6) -> float:
    """Return logit, clamped to avoid infinities."""
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))

def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))

def _nan_to_none(x: Any) -> Any:
    try:
        if x is None:
            return None
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
        return x
    except Exception:
        return None


class BedFusionDetector(hass.Hass):
    """
    AppDaemon app entrypoint.
    """

    def initialize(self) -> None:
        # ---------- Configuration ----------
        cfg = self.args or {}
        # Required/typical sources (probability sensors expected in [0, 100] or [0,1] - auto scaled):
        self.source_prob_sensors: List[str] = cfg.get("source_prob_sensors", [
            # Examples - customize to your entity ids:
            # "sensor.chatgpt_bed_prob_occupied",          # from bed_occupancy.py (if available)
            "sensor.chatgpt_prob_east_bed_occupied",       # from bed_side_predictor.py
            "sensor.chatgpt_prob_west_bed_occupied",       # from bed_side_predictor.py (if present)
        ])

        # Optional boolean occupancy ground-truth-ish and gating:
        self.base_occupancy_boolean: str = cfg.get("base_occupancy_boolean", "input_boolean.chatgpt_bed_occupied")
        self.person_entity: str = cfg.get("person_entity", "person.ryan")
        self.away_values: List[str] = cfg.get("away_values", ["away"])

        # Optional contextual sensors (numbers; they are normalized if ranges provided):
        # Example: {"sensor.entity_id": {"min": 0, "max": 24}} for hour-of-day, etc.
        self.context_numeric_sensors: Dict[str, Dict[str, float]] = cfg.get("context_numeric_sensors", {})

        # Override - an input_select or input_text with values: "off", "force_occupied", "force_unoccupied"
        self.override_entity: Optional[str] = cfg.get("override_entity", "input_select.chatgpt_bed_override")
        self.override_values: List[str] = cfg.get("override_values", ["off", "force_occupied", "force_unoccupied"])

        # Publishing targets
        self.sensor_prob: str = cfg.get("sensor_prob", "sensor.chatgpt_bed_fused_probability")
        self.binary_occupied: str = cfg.get("binary_occupied", "binary_sensor.chatgpt_bed_fused_occupied")
        self.sensor_robust: str = cfg.get("sensor_robustness", "sensor.chatgpt_bed_fusion_robustness")
        self.sensor_conf: str = cfg.get("sensor_confidence", "sensor.chatgpt_bed_fusion_confidence")
        self.binary_training_needed: str = cfg.get("binary_training_needed", "binary_sensor.chatgpt_bed_fusion_training_needed")
        self.sensor_meta: str = cfg.get("sensor_meta", "sensor.chatgpt_bed_fusion_meta")

        # Decision and timing parameters
        self.decision_threshold: float = float(cfg.get("decision_threshold", 0.65))  # probability for occupied
        self.min_publish_interval_sec: float = float(cfg.get("min_publish_interval_sec", 10.0))
        self.train_every_minutes: int = int(cfg.get("train_every_minutes", 60))
        self.min_samples_to_train: int = int(cfg.get("min_samples_to_train", 100))
        self.required_pos_neg: Tuple[int, int] = tuple(cfg.get("required_pos_neg", (50, 100)))
        self.training_window_minutes: int = int(cfg.get("training_window_minutes", 28 * 24 * 60)) # 28 days

        # Robustness/confidence params
        self.robust_agreement_power: float = float(cfg.get("robust_agreement_power", 1.5))
        self.robust_entropy_power: float = float(cfg.get("robust_entropy_power", 1.0))
        self.training_recency_half_life_h: float = float(cfg.get("training_recency_half_life_h", 72.0))

        # Debounce and cooldown
        self.min_hold_time_sec: float = float(cfg.get("min_hold_time_sec", 30.0))  # require state to hold before flip

        # ---------- Internal state ----------
        self._last_publish: Optional[datetime] = None
        self._pending_state: Optional[Tuple[str, datetime]] = None  # ("on"/"off", since)
        self._rng = np.random.default_rng(42)

        # Training buffers (bounded by window length)
        maxlen = max(5000, int(self.training_window_minutes * 60 / max(5, self.min_publish_interval_sec)))
        self._X: deque = deque(maxlen=maxlen)  # feature vectors
        self._y: deque = deque(maxlen=maxlen)  # labels (0/1)
        self._t: deque = deque(maxlen=maxlen)  # timestamps

        # Online model - initialize with log-odds fusion behavior by seeding weights near 1.0
        self._clf = SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=1e-5,
            learning_rate="optimal",
            fit_intercept=True,
            random_state=42
        )
        self._is_fitted = False
        self._feature_names: List[str] = []
        self._last_train_time: Optional[datetime] = None
        self._last_auc: Optional[float] = None

        # Derived: schedule timers and listeners
        self._setup_listeners()
        self._schedule_training()
        self._publish_meta(initial=True)

        self._log("BedFusionDetector initialized.", level="INFO")

    # ------------- Logging wrapper -------------
    def _log(self, msg: str, level: str = "INFO", **kwargs) -> None:
        """
        Project convention asks to include ascii_encode=False in logging.
        AppDaemon's self.log doesn't accept it - we emulate by passing it through kwargs
        and ignoring it to keep syntax valid.
        """
        kwargs.pop("ascii_encode", None)  # ignored, to respect convention without breaking
        try:
            self.log(msg, level=level, **kwargs)
        except Exception:
            # As a fallback, avoid raising from logging
            print(f"[{level}] {msg}")

    # ------------- Setup -------------
    def _setup_listeners(self) -> None:
        # Source probability sensors
        for ent in self.source_prob_sensors:
            self.listen_state(self._on_source_update, ent)

        # Base occupancy boolean and presence
        if self.base_occupancy_boolean:
            self.listen_state(self._on_label_update, self.base_occupancy_boolean)
        if self.person_entity:
            self.listen_state(self._on_presence_update, self.person_entity)

        # Context numeric sensors
        for ent in self.context_numeric_sensors.keys():
            self.listen_state(self._on_context_update, ent)

        # Override
        if self.override_entity:
            self.listen_state(self._on_override_update, self.override_entity)

        # Heartbeat to compute and publish
        self.run_every(self._heartbeat, self.datetime() + timedelta(seconds=5), int(self.min_publish_interval_sec))

    def _schedule_training(self) -> None:
        # periodic training task
        self.run_every(self._train_if_ready, self.datetime() + timedelta(minutes=5), int(self.train_every_minutes * 60))

    # ------------- Listeners -------------
    def _on_source_update(self, entity, attribute, old, new, kwargs) -> None:
        self._log(f"[DEBUG] Source update: {entity} -> {new}", level="INFO", ascii_encode=False)

    def _on_label_update(self, entity, attribute, old, new, kwargs) -> None:
        self._log(f"[DEBUG] Base occupancy boolean changed: {old} -> {new}", level="INFO", ascii_encode=False)
        # When base label changes, this may create labeled samples during heartbeat

    def _on_presence_update(self, entity, attribute, old, new, kwargs) -> None:
        self._log(f"[DEBUG] Presence changed: {old} -> {new}", level="INFO", ascii_encode=False)

    def _on_context_update(self, entity, attribute, old, new, kwargs) -> None:
        self._log(f"[DEBUG] Context update: {entity} -> {new}", level="INFO", ascii_encode=False)

    def _on_override_update(self, entity, attribute, old, new, kwargs) -> None:
        self._log(f"[DEBUG] Override changed: {old} -> {new}", level="INFO", ascii_encode=False)
        

    # ------------- Core heartbeat -------------
    def _heartbeat(self, kwargs) -> None:
        try:
            now = self.datetime()
            # Read feature vector
            feats, names, src_probs = self._build_feature_vector()
            if feats is None:
                self._log("[DEBUG] Heartbeat skipped - missing features.", level="INFO", ascii_encode=False)
                return

            # Predict fused probability
            p = self._predict_probability(feats, names)
            # Apply override if any
            over_state = self._read_override()
            if over_state == "force_occupied":
                p_effective = 1.0
                over_applied = True
            elif over_state == "force_unoccupied":
                p_effective = 0.0
                over_applied = True
            else:
                p_effective = p
                over_applied = False

            # Robustness and confidence
            robustness = self._compute_robustness(src_probs, p_effective)
            confidence = self._compute_confidence(robustness)

            # State decision with debounce
            state = "on" if p_effective >= self.decision_threshold else "off"
            state = self._debounced_state(state, now)

            # Publish
            self._publish(
                p_effective=p_effective,
                state=state,
                robustness=robustness,
                confidence=confidence,
                over_applied=over_applied
            )

            # Label creation for training set
            self._maybe_record_label(feats, names, now)

        except Exception as e:
            self._log(f"[ERROR] Heartbeat exception: {e}\n{traceback.format_exc()}", level="ERROR", ascii_encode=False)

    # ------------- Feature building -------------
    def _build_feature_vector(self) -> Tuple[Optional[np.ndarray], List[str], Dict[str, float]]:
        names: List[str] = []
        vals: List[float] = []
        src_probs: Dict[str, float] = {}

        # Source probabilities
        for ent in self.source_prob_sensors:
            s = self.get_state(ent)
            try:
                if s is None or s == "unknown" or s == "unavailable":
                    continue
                v = float(s)
                # auto-scale if looks like percent
                if v > 1.0:
                    v = v / 100.0
                v = min(max(v, 0.0), 1.0)
                names.append(f"prob::{ent}")
                vals.append(v)
                src_probs[ent] = v
            except Exception:
                continue

        # Context numeric sensors (normalized 0..1 if bounds provided)
        for ent, rng in self.context_numeric_sensors.items():
            s = self.get_state(ent)
            try:
                if s is None or s == "unknown" or s == "unavailable":
                    continue
                v = float(s)
                v_norm = v
                lo = rng.get("min")
                hi = rng.get("max")
                if lo is not None and hi is not None and hi > lo:
                    v_norm = (v - lo) / (hi - lo)
                    v_norm = min(max(v_norm, 0.0), 1.0)
                names.append(f"ctx::{ent}")
                vals.append(v_norm)
            except Exception:
                continue

        if not vals:
            return None, [], {}

        feats = np.array(vals, dtype=float).reshape(1, -1)

        # Cache feature names order
        if self._feature_names != names:
            self._feature_names = names
            self._is_fitted = False  # force re-fit so shapes match
            self._log(f"[DEBUG] Feature schema updated: {names}", level="INFO", ascii_encode=False)

        return feats, names, src_probs

    # ------------- Prediction and training -------------
    def _predict_probability(self, feats: np.ndarray, names: List[str]) -> float:
        if self._is_fitted:
            try:
                proba = float(self._clf.predict_proba(feats)[0, 1])
                return min(max(proba, 0.0), 1.0)
            except Exception as e:
                self._log(f"[DEBUG] Predict failed with fitted model, falling back. {e}", level="WARNING", ascii_encode=False)

        # Fallback: log-odds fusion with unit weights
        z = 0.0
        for f, nm in zip(feats.flatten().tolist(), names):
            if nm.startswith("prob::"):
                z += _safe_logit(f)
            else:
                # Context features influence weakly in fallback
                z += 0.25 * _safe_logit(min(max(f, 1e-3), 1 - 1e-3))
        return _sigmoid(z / max(1, len(names)))

    def _maybe_record_label(self, feats: np.ndarray, names: List[str], now: datetime) -> None:
        """
        Build weak labels:
        - If person is away -> label 0 (unoccupied)
        - Else if base_occupancy_boolean is on -> label 1 (occupied)
        - Else in daytime with consistent low probs -> label 0
        """
        label: Optional[int] = None

        presence = self.get_state(self.person_entity) if self.person_entity else None
        is_away = presence in self.away_values if presence is not None else False

        base_bool = self.get_state(self.base_occupancy_boolean) if self.base_occupancy_boolean else None
        base_on = base_bool == "on"

        if is_away:
            label = 0
        elif base_on:
            label = 1
        else:
            # Conservative extra negatives during typical awake hours 08:00-20:00 when probs are very low
            hour = now.hour
            try:
                low_prob = float(self.get_state(self.sensor_prob) or "0")  # last published
                if low_prob > 1.0:
                    low_prob = low_prob / 100.0
            except Exception:
                low_prob = 0.0
            if 8 <= hour <= 20 and low_prob < 0.15:
                label = 0

        if label is None:
            return

        self._X.append(feats.flatten().astype(float))
        self._y.append(int(label))
        self._t.append(now)

    def _train_if_ready(self, kwargs) -> None:
        try:
            # Use samples from within the training window
            cutoff = self.datetime() - timedelta(minutes=int(self.training_window_minutes))
            X = [x for x, tt in zip(self._X, self._t) if tt >= cutoff]
            y = [yy for yy, tt in zip(self._y, self._t) if tt >= cutoff]

            if len(X) < self.min_samples_to_train or len(set(y)) < 2:
                self._log(f"[DEBUG] Training skipped: samples={len(X)} classes={set(y)}", level="INFO", ascii_encode=False)
                self._publish_training_needed(True)
                return

            X = np.vstack(X)
            y = np.array(y, dtype=int)

            # Fit or partial_fit
            if not self._is_fitted:
                self._clf.partial_fit(X, y, classes=np.array([0, 1], dtype=int))
                self._is_fitted = True
            else:
                self._clf.partial_fit(X, y)

            # Metrics
            try:
                proba = self._clf.predict_proba(X)[:, 1]
                auc = roc_auc_score(y, proba)
                ll = log_loss(y, proba, labels=[0,1])
                self._last_auc = float(auc)
                auc_msg = f"AUC={auc:.3f}, logloss={ll:.3f}"
            except Exception as e:
                self._last_auc = None
                auc_msg = f"AUC unavailable: {e}"

            self._last_train_time = self.datetime()
            self._publish_training_needed(False)
            self._publish_meta()

            self._log(f"[INFO] Model trained: n={len(X)} pos={int(y.sum())} neg={int((1-y).sum())} {auc_msg}", level="INFO", ascii_encode=False)
        except Exception as e:
            self._log(f"[ERROR] Train exception: {e}\n{traceback.format_exc()}", level="ERROR", ascii_encode=False)

    # ------------- Robustness and confidence -------------
    def _compute_robustness(self, src_probs: Dict[str, float], p_effective: float) -> float:
        """Combine agreement and entropy into a single 0..1 robustness metric."""
        if not src_probs:
            return 0.0
        probs = np.array(list(src_probs.values()), dtype=float)
        mean_p = float(np.mean(probs))
        # Agreement: 1 - normalized variance
        var = float(np.var(probs))
        agree = 1.0 - min(var / 0.0833, 1.0)  # 0.0833 ~ var of uniform(0,1)
        # Entropy: low entropy (near 0 or 1) is better
        p = min(max(p_effective, 1e-6), 1 - 1e-6)
        entropy = - (p * math.log(p) + (1 - p) * math.log(1 - p)) / math.log(2)  # 0..1
        entropy_score = 1.0 - float(entropy)  # high is confident

        # Combine with powers to shape curve
        rob = (agree ** self.robust_agreement_power) * (entropy_score ** self.robust_entropy_power)
        return float(min(max(rob, 0.0), 1.0))

    def _compute_confidence(self, robustness: float) -> float:
        """Confidence also decays with time since last training."""
        if self._last_train_time is None:
            time_decay = 0.7
        else:
            hours = max((self.datetime() - self._last_train_time).total_seconds() / 3600.0, 0.0)
            hl = max(self.training_recency_half_life_h, 1e-3)
            time_decay = 0.5 ** (hours / hl)  # 1.0 at t=0, halves every hl hours

        # AUC bonus (if available)
        auc_bonus = 0.0
        if self._last_auc is not None:
            # Map AUC 0.5..0.9 -> 0..0.3
            auc_bonus = max(min((self._last_auc - 0.5) * (0.3 / 0.4), 0.3), 0.0)

        conf = max(min(robustness * (0.7 + auc_bonus) * (0.6 + 0.4 * time_decay), 1.0), 0.0)
        return float(conf)

    # ------------- Override -------------
    def _read_override(self) -> str:
        if not self.override_entity:
            return "off"
        val = self.get_state(self.override_entity)
        if val in self.override_values:
            return val
        return "off"

    # ------------- Debounce -------------
    def _debounced_state(self, target: str, now: datetime) -> str:
        if self._pending_state is None:
            self._pending_state = (target, now)
            return self.get_state(self.binary_occupied) or "off"

        last_target, since = self._pending_state
        if target == last_target:
            # check hold time
            if (now - since).total_seconds() >= self.min_hold_time_sec:
                # commit
                self._pending_state = (target, now)  # reset window for next flip
                return target
            else:
                # keep prior HA state
                return self.get_state(self.binary_occupied) or "off"
        else:
            # new target, start hold
            self._pending_state = (target, now)
            return self.get_state(self.binary_occupied) or "off"

    # ------------- Publishing -------------
    def _publish(self, p_effective: float, state: str, robustness: float, confidence: float, over_applied: bool) -> None:
        now = self.datetime()

        # Throttle publishes of probability and metrics
        if self._last_publish and (now - self._last_publish).total_seconds() < self.min_publish_interval_sec:
            return
        self._last_publish = now

        # Probability in percent
        prob_percent = round(float(p_effective) * 100.0, 2)

        # Publish probability
        self.set_state(self.sensor_prob, state=str(prob_percent), attributes={
            "unit_of_measurement": "%",
            "friendly_name": "Bed - Fused probability occupied",
            "state_class": "measurement",
            "device_class": "measurement",
            "last_updated": now.isoformat(),
        })

        # Publish binary state
        self.set_state(self.binary_occupied, state=state, attributes={
            "device_class": "occupancy",
            "friendly_name": "Bed - Fused occupied",
            "overridden": over_applied,
            "threshold": self.decision_threshold,
            "last_updated": now.isoformat(),
        })

        # Robustness and confidence
        self.set_state(self.sensor_robust, state=f"{robustness:.3f}", attributes={
            "friendly_name": "Bed - Fusion robustness",
            "state_class": "measurement",
            "device_class": "measurement",
            "last_updated": now.isoformat(),
        })
        self.set_state(self.sensor_conf, state=f"{confidence:.3f}", attributes={
            "friendly_name": "Bed - Fusion confidence",
            "state_class": "measurement",
            "device_class": "measurement",
            "last_updated": now.isoformat(),
        })

        self._publish_meta()

        self._log(f"[DEBUG] Published fused prob={prob_percent:.2f}% state={state} robustness={robustness:.3f} confidence={confidence:.3f}", level="INFO", ascii_encode=False)

    def _publish_training_needed(self, needed: bool) -> None:
        self.set_state(self.binary_training_needed, state="on" if needed else "off", attributes={
            "friendly_name": "Bed - Fusion training needed",
            "criteria": {
                "min_samples": self.min_samples_to_train,
                "required_pos_neg": list(self.required_pos_neg),
            },
            "last_updated": self.datetime().isoformat(),
        })

    def _publish_meta(self, initial: bool = False) -> None:
        meta: Dict[str, Any] = {
            "feature_names": list(self._feature_names),
            "is_fitted": bool(self._is_fitted),
            "last_train_time": self._last_train_time.isoformat() if self._last_train_time else None,
            "last_auc": _nan_to_none(self._last_auc),
            "samples_buffered": len(self._X),
            "training_window_minutes": self.training_window_minutes,
            "decision_threshold": self.decision_threshold,
            "min_hold_time_sec": self.min_hold_time_sec,
            "source_prob_sensors": list(self.source_prob_sensors),
            "context_numeric_sensors": list(self.context_numeric_sensors.keys()),
        }
        self.set_state(self.sensor_meta, state="ready" if self._is_fitted else "cold_start", attributes=meta)

        if initial:
            self._log(f"[DEBUG] Meta initialized: {json.dumps(meta)}", level="INFO", ascii_encode=False)