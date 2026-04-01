import appdaemon.plugins.hass.hassapi as hass
import statistics
from datetime import datetime, timedelta, time
import numpy as np
from scipy.optimize import curve_fit
import asyncio
import psycopg2
from scipy.signal import butter, filtfilt
from dateutil import parser


class BedOccupancy(hass.Hass):
    """
    Bed occupancy detection and calibration app (kg).

    - Automatically calibrates zero_offset and scale_factor from prior-day history
    - Converts raw ADC to kg via zero_offset & scale_factor
    - Smoothed medians, absolute-delta with hysteresis
    - Day/night baselines updated from history twice daily
    - Threshold recalculated twice daily when unoccupied
    - Baseline drift tolerance, clamping, and skip when occupied
    """

    def initialize(self):
        self.hysteresis_score = 0
        self.calibrated = False
        self.baseline_ready = False  # guard _raw_update until first baseline

        self.drift_model_coeffs = None
        self.last_vacated_time = None

        self.log("[init] Initializing BedOccupancy app", ascii_encode=False)

        self.load_cell = self.args["load_cell_sensor"]
        self.presence = self.args.get("presence_entity")
        self.occupancy_bool = self.args["occupancy_boolean"]
        self.override_entity = self.args.get("override_boolean")
        self.delta_sensor = self.args["delta_sensor"]
        self.threshold_sensor = self.args["threshold_sensor"]
        self.baseline_day_sensor = self.args["baseline_day_sensor"]
        self.baseline_night_sensor = self.args["baseline_night_sensor"]
        self.input_threshold = self.args.get("input_threshold_entity")
        self.buffer_size = int(self.args.get("buffer_size", 5))

        self.zero_offset = float(self.args.get("zero_offset", 0.0))
        self.scale = float(self.args.get("scale_factor", 1.0))
        self.decay = float(self.args.get("decay", 0.85))
        self.zero_drift = float(self.args.get("zero_drift_tolerance", 0.1))
        self.min_empty = float(self.args.get("min_empty_kg", 0.0))
        self.max_empty = float(self.args.get("max_empty_kg", 5.0))

        self.drift_model_order = int(self.args.get("drift_model_order", 2))
        self.drift_train_days = int(self.args.get("drift_train_days", 14))
        self.drift_max_unoccupied_sec = int(
            self.args.get("drift_max_unoccupied_sec", 10800)
        )  # 6 hours
        self.drift_apply_max_sec = int(self.args.get("drift_apply_max_sec", 5400))  # 3 hours

        self.listen_state(self._on_occupancy_change, "input_boolean.chatgpt_bed_occupied")
        self.run_in(self._train_drift_model, 120)
        self.run_daily(self._train_drift_model, time(13, 15))

        self.override_active = False
        if self.override_entity:
            self.override_active = self.get_state(self.override_entity) == "on"
            self.listen_state(self._on_override_toggle, self.override_entity)

        self.create_task(self._init_hysteresis())

        self.night_start = int(self.args.get("night_start_hour", 22))
        self.night_end = int(self.args.get("night_end_hour", 8))

        self.buffer = []
        self.fast_buffer = []
        self.fast_size = max(3, self.buffer_size // 2)
        self.occupied = self.get_state(self.occupancy_bool) == "on"

        # Always listen raw updates but guard until baseline_ready
        self.listen_state(self._raw_update, self.load_cell)

        if self.input_threshold:
            self.listen_event(
                self._on_manual_threshold,
                "call_service",
                domain="input_button",
                service="press",
                entity_id=self.input_threshold,
            )

        self.run_daily(self._auto_calibrate, time(14, 0))
        self.run_daily(self._auto_calibrate, time(20, 0))
        self.run_in(
            self._update_baseline_from_history,
            self.args.get("run_in_after_startup", 90),
        )
        self.run_daily(self._update_threshold_from_history, time(11, 0))
        self.run_daily(self._update_threshold_from_history, time(20, 0))
        self.run_daily(self._update_baseline_from_history, time(11, 5))
        self.run_daily(self._update_baseline_from_history, time(20, 5))
        self.run_every(self._update_hysteresis, time(0, 0), timedelta(hours=6))
        self.run_in(self._auto_calibrate, 5, kwargs={})
        self.run_in(self._update_baseline_from_history, 30, kwargs={})
        self.run_in(self._update_threshold_from_history, 60, kwargs={})

        self.log("[init] BedOccupancy initialized", ascii_encode=False)

    def _on_occupancy_change(self, entity, attribute, old, new, kwargs=None):
        if new == "off":
            self.last_vacated_time = self.datetime()

    def _exp_drift(self, t, a, b):
        return a * (1 - np.exp(-b * t))

    def _set_paired_state(
        self,
        base_entity_id: str,
        raw_value: float,
        kg_value: float | None = None,
        unit: str = "kg",
    ):
        """Updates both raw and kg sensors as numeric measurement entities.

        - `<base_entity_id>_raw` is always unitless ADC "raw" units, state_class measurement.
        - `<base_entity_id>` is optional and only created when `kg_value` is not None.
        - When `unit == 'kg'` we apply `device_class: weight`.
        """

        try:
            self.set_state(
                f"{base_entity_id}_raw",
                state=round(raw_value, 2),
                attributes={
                    "unit_of_measurement": "raw",
                    "state_class": "measurement",
                },
            )
        except Exception as e:
            self.log(
                f"[set_paired_state] Failed to update {base_entity_id}_raw: {e}",
                level="WARNING",
                ascii_encode=False,
            )

        if kg_value is not None:
            attrs = {
                "unit_of_measurement": unit,
                "state_class": "measurement",
            }
            if unit == "kg":
                attrs["device_class"] = "weight"
            try:
                self.set_state(
                    base_entity_id,
                    state=round(kg_value, 2),
                    attributes=attrs,
                )
            except Exception as e:
                self.log(
                    f"[set_paired_state] Failed to update {base_entity_id}: {e}",
                    level="WARNING",
                    ascii_encode=False,
                )

    def _on_override_toggle(self, entity, attribute, old, new, kwargs):
        now = datetime.now().isoformat()
        self.log(f"[override] Transition {old} → {new} at {now}", ascii_encode=False)
        self.set_state(
            "sensor.chatgpt_bed_override_event",
            state=new,
            attributes={
                "timestamp": now,
                "from": old,
                "to": new,
            },
        )
        self.override_active = new == "on"
        if self.override_active:
            self.log(
                "[override] Manual override ENABLED. Auto detection suspended.",
                ascii_encode=False,
            )
        else:
            self.log(
                "[override] Manual override DISABLED. Resuming auto detection.",
                ascii_encode=False,
            )
            self.buffer.clear()
            self.fast_buffer.clear()
            raw = self.get_state(self.load_cell)
            try:
                self._raw_update(self.load_cell, None, None, raw)
            except Exception as e:
                self.log(
                    f"[override] Error triggering raw update after override off: {e}",
                    level="WARNING",
                    ascii_encode=False,
                )

    def _on_manual_threshold(self, event_name, data, kwargs):
        self.log("[manual] Manual threshold trigger", ascii_encode=False)
        self.run_in(self._update_threshold_from_history, 5, kwargs={})

    async def _auto_calibrate(self, kwargs):
        """Compute zero_offset and scale_factor using raw history.

        Calibration is done entirely in raw ADC units, then converted via a
        target occupied weight to derive the scale factor. We only expose
        internal calibration values as simple numeric sensors without
        device_class/state_class to avoid HA 400s on helpers.
        """

        self.log(
            f"[calib] Auto-calibrating zero_offset & scale_factor for {self.load_cell}",
            ascii_encode=False,
        )
        entries = await self._get_history_chunked(self.load_cell, days=14)
        raw_vals = [
            float(e["state"]) for e in entries if self._is_valid_state(e.get("state"))
        ]
        if not raw_vals:
            self.log("[calib] No valid raw entries, skipping", ascii_encode=False)
            return

        # Occupancy mapping
        occ_entries = await self._get_history_chunked(self.occupancy_bool, days=14)
        occ_states = {
            self.convert_utc(e["last_changed"]): e["state"] == "on"
            for e in occ_entries
            if "state" in e
        }

        def is_occupied(ts: datetime) -> bool:
            return occ_states.get(max((t for t in occ_states if t <= ts), default=ts), False)

        # Split raw into empty vs occupied
        empty_vals = [
            rv
            for e, rv in zip(entries, raw_vals)
            if not is_occupied(self.convert_utc(e["last_changed"]))
        ]
        occ_vals = [
            rv
            for e, rv in zip(entries, raw_vals)
            if is_occupied(self.convert_utc(e["last_changed"]))
        ]

        if not empty_vals or not occ_vals:
            self.log(
                "[calib] Insufficient samples for calibration, skipping",
                ascii_encode=False,
            )
            return

        # MAD filter only (no high-pass)
        empty_vals, mad_empty, *_ = self._mad_filter(empty_vals, "calib_empty")
        occ_vals, mad_occ, *_ = self._mad_filter(occ_vals, "calib_occ")

        med_empty = statistics.median(empty_vals)
        med_occ = statistics.median(occ_vals)

        # Compute raw-per-kg scale
        target_kg = float(self.args.get("target_occupied_weight", 80.0))
        diff_raw = abs(med_occ - med_empty)
        new_scale = diff_raw / max(target_kg, 1e-6)  # raw units per kg

        # Blend parameters
        days_present = len({self.convert_utc(e["last_changed"]).date() for e in entries})
        required_days = int(self.args.get("calib_days", 14))
        alpha = (
            1.0
            if days_present >= required_days
            else float(self.args.get("calib_alpha", 0.2))
        )
        self.log(
            f"[calib] Using {days_present} days (need {required_days}) → α={alpha:.2f}",
            ascii_encode=False,
        )

        self.zero_offset = med_empty
        self.scale = self.scale * (1 - alpha) + new_scale * alpha
        self.calibrated = True

        self.log(
            f"[calib] Calibrated: zero_offset={self.zero_offset:.2f}, scale={self.scale:.2f}",
            ascii_encode=False,
        )

        # Keep zero_offset in raw units, but optionally align to the current baseline
        hist_base = self._get_baseline()
        if hist_base is not None:
            self.log(
                f"[calib] Overwriting zero_offset {self.zero_offset:.2f} → history baseline {hist_base:.2f}",
                ascii_encode=False,
            )
            self.zero_offset = hist_base
        self.log(
            f"[calib] Final zero_offset={self.zero_offset:.2f}, scale={self.scale:.2f}",
            ascii_encode=False,
        )

        # Expose calibration values as simple numeric sensors, WITHOUT device_class/state_class
        try:
            self.set_state(
                "sensor.chatgpt_bed_zero_offset_raw",
                state=round(self.zero_offset, 2),
                attributes={
                    "unit_of_measurement": "raw",
                },
            )
        except Exception as e:
            self.log(
                f"[calib] Failed to publish zero_offset_raw: {e}",
                level="WARNING",
                ascii_encode=False,
            )
        try:
            self.set_state(
                "sensor.chatgpt_bed_scale_factor_raw",
                state=round(self.scale, 6),
                attributes={
                    "unit_of_measurement": "unitless",
                },
            )
        except Exception as e:
            self.log(
                f"[calib] Failed to publish scale_factor_raw: {e}",
                level="WARNING",
                ascii_encode=False,
            )

        self.listen_state(self._raw_update, self.load_cell)

    def _get_history_via_sql(self, entity_id, start_time, end_time):
        self.log(
            f"[sql] SQL querying for {entity_id}", level="INFO", ascii_encode=False
        )

        if not self.args.get("use_sql_history", False):
            return []

        db_url = self.args.get("db_url")
        if not db_url:
            self.log(
                "[sql] Missing 'db_url' in apps.yaml",
                level="ERROR",
                ascii_encode=False,
            )
            return []

        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            query = """
                SELECT s.last_updated_ts, s.state
                FROM states s
                JOIN states_meta m ON s.metadata_id = m.metadata_id
                WHERE m.entity_id = %s
                    AND s.last_updated_ts >= %s
                    AND s.last_updated_ts < %s
                    AND s.state NOT IN ('unknown', 'unavailable')
                ORDER BY s.last_updated_ts ASC
            """
            cur.execute(
                query,
                (entity_id, start_time.timestamp(), end_time.timestamp()),
            )
            results = cur.fetchall()
            cur.close()
            conn.close()
            return [
                {
                    "last_changed": datetime.fromtimestamp(float(r[0])),
                    "state": r[1],
                }
                for r in results
            ]
        except Exception as e:
            import traceback

            self.log(
                f"[sql] Error fetching history for {entity_id}: {e}",
                level="ERROR",
                ascii_encode=False,
            )
            self.log(traceback.format_exc(), level="ERROR", ascii_encode=False)
            return []

    async def _get_history_chunked(self, entity_id, days=14):
        now = await self.run_in_executor(self.datetime)
        if self.args.get("use_sql_history", False):
            start = now - timedelta(days=days)
            results = self._get_history_via_sql(entity_id, start, now)
            if results:
                return results
            else:
                self.log(
                    "[sql] SQL query failed or returned no results, falling back to HA API",
                    level="WARNING",
                    ascii_encode=False,
                )

        self.log(
            f"[get_history_chunked] HA Chunk History querying for {entity_id}",
            level="INFO",
            ascii_encode=False,
        )
        history = []
        start_batch = await self.run_in_executor(self.datetime)

        async def fetch_chunk(start, end):
            t0 = await self.run_in_executor(self.datetime)
            try:
                result = await self.get_history(
                    entity_id=entity_id, start_time=start, end_time=end
                )
                duration = (
                    await self.run_in_executor(self.datetime) - t0
                ).total_seconds()
                # self.log(f"[chunk] {entity_id} {start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%H:%M')} fetched in {duration:.2f}s", ascii_encode=False)
                return sum(result or [], [])
            except Exception as e:
                duration = (
                    await self.run_in_executor(self.datetime) - t0
                ).total_seconds()
                self.log(
                    f"[chunk] FAILED {entity_id} {start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%H:%M')} after {duration:.2f}s: {e}",
                    level="WARNING",
                    ascii_encode=False,
                )
                return []

        tasks = []
        for i in range(days):
            base = now - timedelta(days=i + 1)
            for j in range(0, 24, 6):  # four 6-hour chunks per day
                start = base.replace(hour=j, minute=0, second=0, microsecond=0)
                end = start + timedelta(hours=6)
                tasks.append(fetch_chunk(start, end))

        results = await asyncio.gather(*tasks)
        for r in results:
            history.extend(r)

        total_duration = (
            await self.run_in_executor(self.datetime) - start_batch
        ).total_seconds()
        self.log(
            f"[chunk] {entity_id} total fetch time: {total_duration:.2f}s",
            ascii_encode=False,
        )

        return history

    def _convert(self, raw):
        """Safely convert raw ADC to kg with scale sanity check"""
        try:
            kg = (raw - self.zero_offset) / self.scale
            if abs(kg) > 1000:
                self.log(
                    f"[convert] ⚠️ Computed weight out of range: {kg:.2f}kg",
                    level="WARNING",
                    ascii_encode=False,
                )
                return None
            return kg
        except Exception as e:
            self.log(
                f"[convert] ⚠️ Conversion error: {e}",
                level="WARNING",
                ascii_encode=False,
            )
            return None

    async def _update_baseline_from_history(self, kwargs):
        self.log(
            "[baseline] Calculating baselines via MAD-filtered history (exp-weighted)",
            ascii_encode=False,
        )
        raw_entries = await self._get_history_chunked(self.load_cell, days=14)
        occ_entries = await self._get_history_chunked(self.occupancy_bool, days=14)

        occ_states = {
            self.convert_utc(e["last_changed"]): e["state"] == "on"
            for e in occ_entries
            if "state" in e
        }

        def is_occupied(ts):
            nearest = max((t for t in occ_states if t <= ts), default=None)
            return occ_states.get(nearest, False)

        day_buckets: dict = {}
        night_buckets: dict = {}
        for e in raw_entries:
            try:
                raw_val = float(e["state"])
                ts = self.convert_utc(e["last_changed"])
                if is_occupied(ts):
                    continue
                bucket = (
                    night_buckets
                    if self.night_start <= ts.hour or ts.hour < self.night_end
                    else day_buckets
                )
                key = ts.date()
                bucket.setdefault(key, []).append(raw_val)
            except Exception:
                continue

        def weighted_baseline_raw(buckets, label):
            daily = []
            for day, vals in sorted(buckets.items()):
                vals, *_ = self._mad_filter(vals, f"{label}_{day.isoformat()}")
                if vals:
                    med = statistics.median(vals)
                    daily.append(med)
            if not daily:
                return None
            weights = [self.decay ** i for i in reversed(range(len(daily)))]
            return float(np.average(daily, weights=weights))

        day_raw = weighted_baseline_raw(day_buckets, "day")
        night_raw = weighted_baseline_raw(night_buckets, "night")

        if day_raw is not None:
            self._set_baseline(self.baseline_day_sensor, day_raw)
        if night_raw is not None:
            self._set_baseline(self.baseline_night_sensor, night_raw)
        self.baseline_ready = True

    def _iqr_estimate(self):
        try:
            self.log("[iqr] Using chunked history for IQR estimate", ascii_encode=False)
            entries = asyncio.run(
                self._get_history_chunked(self.delta_sensor, days=14)
            ) or []
            entries = sum(entries, [])
            deltas = []
            for e in entries:
                try:
                    deltas.append(abs(float(e.get("state"))))
                except (TypeError, ValueError):
                    continue
            q1, q3 = np.percentile(deltas, [25, 75])
            iqr = q3 - q1
            self.log(
                f"[iqr] IQR estimation: Q1={q1:.2f}kg, Q3={q3:.2f}kg, IQR={iqr:.2f}kg",
                ascii_encode=False,
            )
            return iqr
        except Exception as e:
            self.log(
                f"[iqr] Fallback IQR=100.0 due to error: {e}", ascii_encode=False
            )
            return 100.0

    def _is_night(self):
        h = datetime.now().hour
        return h >= self.night_start or h < self.night_end

    def _get_baseline(self):
        sensor = (
            self.baseline_night_sensor + "_raw"
            if self._is_night()
            else self.baseline_day_sensor + "_raw"
        )
        try:
            return float(self.get_state(sensor))
        except Exception:
            return None

    def _set_baseline(self, sensor, new_base):
        self.occupied = self.get_state(self.occupancy_bool) == "on"
        old = self._get_baseline()
        if self.occupied or old is None:
            value = new_base
        else:
            max_empty_raw = (self.max_empty * self.scale) + self.zero_offset
            min_empty_raw = (self.min_empty * self.scale) + self.zero_offset
            new_base = max(min(new_base, max_empty_raw), min_empty_raw)
            if abs(new_base - old) <= self.zero_drift:
                self.log(
                    f"[baseline] Δ{new_base - old:.3f} raw within ±{self.zero_drift} raw → IGNORE",
                    ascii_encode=False,
                )
                return
            alpha = 0.1
            value = old * (1 - alpha) + new_base * alpha
        value_kg = (value - self.zero_offset) / self.scale
        self._set_paired_state(sensor, value, value_kg)
        self.log(
            f"[baseline] {sensor} set to  {value} raw, {value_kg:.2f} kg",
            ascii_encode=False,
        )

    def _set_occupied(self, state):
        """Update boolean occupancy and numeric occupancy sensors."""
        if self.override_active:
            self.log(
                "[override] Active - ignoring _set_occupied() call",
                ascii_encode=False,
            )
            return
        self.occupied = state
        s = "on" if state else "off"
        self.set_state(self.occupancy_bool, state=s)
        try:
            self.set_state(
                "sensor.chatgpt_bed_occupied_numeric",
                state=1 if state else 0,
                attributes={
                    "unit_of_measurement": "state",
                    "state_class": "measurement",
                },
            )
        except Exception as e:
            self.log(
                f"[occupancy] Failed to set numeric occupancy sensor: {e}",
                level="WARNING",
                ascii_encode=False,
            )
        self.log(
            f"[occupancy] {'OCC' if state else 'UNOCC'}",
            ascii_encode=False,
        )

    def _raw_update(self, entity, attribute, old, new, kwargs=None):
        """Process raw updates only after calibration and baseline are ready."""
        if not self.baseline_ready or not self.calibrated:
            return

        try:
            raw = float(new)
        except Exception:
            self.log(f"[raw] Invalid input: {new}", level="WARNING", ascii_encode=False)
            return
        if not self.calibrated or self.scale == 0:
            self.log(
                "[raw] Calibration not complete or self.scale=0, skipping conversion",
                ascii_encode=False,
            )
            return

        raw = self._apply_drift_correction(raw)

        if self.scale is None or self.scale == 0:
            self.log(
                "[raw] Calibration not complete self.scale=0 or None, skipping conversion",
                ascii_encode=False,
            )
            return
        kg = self._convert(raw)
        if kg is not None and abs(kg) > 1000:
            self.log(
                f"[convert] ⚠️ Weight out of realistic range: {kg:.2f}kg",
                level="WARNING",
                ascii_encode=False,
            )
            return
        if kg is not None:
            try:
                self.set_state(
                    f"{self.load_cell}_kg",
                    state=round(kg, 2),
                    attributes={
                        "unit_of_measurement": "kg",
                        "device_class": "weight",
                        "state_class": "measurement",
                    },
                )
            except Exception as e:
                self.log(
                    f"[raw] Failed to set kg sensor {self.load_cell}_kg: {e}",
                    level="WARNING",
                    ascii_encode=False,
                )

        if not hasattr(self, "ema_baseline"):
            self.ema_baseline = None
        if not hasattr(self, "ema_alpha"):
            self.ema_alpha = float(self.args.get("ema_alpha", 0.05))
        self.ema_baseline = (
            raw
            if self.ema_baseline is None
            else (self.ema_alpha * raw + (1 - self.ema_alpha) * self.ema_baseline)
        )

        tmp_raw = self._convert(raw)
        if raw is None or tmp_raw is None or abs(tmp_raw) > 1000:
            return
        self.buffer.append(raw)
        if len(self.buffer) > self.buffer_size:
            self.buffer.pop(0)
        self.fast_buffer.append(raw)
        if len(self.fast_buffer) > self.fast_size:
            self.fast_buffer.pop(0)

        if len(self.buffer) < self.buffer_size:
            self.log(
                f"[eval] Buffering: {len(self.buffer)}/{self.buffer_size}",
                ascii_encode=False,
            )
            return

        slow_raw = statistics.median(self.buffer)
        fast_raw = statistics.median(self.fast_buffer)
        baseline_raw = self._get_baseline()
        if baseline_raw is None:
            target = (
                self.baseline_night_sensor
                if self._is_night()
                else self.baseline_day_sensor
            )
            self._set_baseline(target, slow_raw)
            return

        delta_raw = abs(slow_raw - baseline_raw)
        delta_kg = delta_raw / self.scale
        self._set_paired_state(self.delta_sensor, delta_raw, delta_kg)

        thr_raw = self._get_threshold()
        thr_kg = thr_raw / self.scale

        slow_kg = (slow_raw - baseline_raw) / self.scale
        fast_kg = (fast_raw - baseline_raw) / self.scale
        baseline_kg = 0.0

        if self.override_active:
            # self.log("[override] Active - skipping detection", ascii_encode=False)
            return
        if self.occupied:
            if (
                delta_raw < (thr_raw - self.hysteresis)
                and abs(fast_raw - baseline_raw) < (thr_raw - self.hysteresis)
            ):
                self._set_occupied(False)
                if (
                    abs(fast_raw - baseline_raw)
                    > (thr_raw - self.hysteresis * 0.5)
                ):
                    self.hysteresis_score += 1
        else:
            if abs(fast_raw - baseline_raw) > (thr_raw + self.hysteresis):
                self._set_occupied(True)
                if (
                    abs(fast_raw - baseline_raw)
                    < (thr_raw + self.hysteresis * 0.5)
                ):
                    self.hysteresis_score += 1

    def _safe_highpass(self, values, label, min_len=30):
        """Apply a Butterworth high-pass filter if enough samples exist."""
        if len(values) < min_len:
            self.log(
                f"[{label}] Skipping Butterworth high-pass filter (raw units) — only {len(values)} raw samples",
                level="WARNING",
                ascii_encode=False,
            )
            return values
        try:
            b, a = butter(2, 0.01, btype="high")
            filtered = filtfilt(b, a, values)
            clamped = np.clip(filtered, -1000, 1000)
            if np.any(clamped != filtered):
                self.log(
                    f"[{label}] Clamped filter output to ±1000kg (range was {filtered.min():.2f}-{filtered.max():.2f})",
                    level="WARNING",
                    ascii_encode=False,
                )
            return clamped.tolist()
        except Exception as e:
            self.log(
                f"[{label}] Filter error: {e}",
                level="ERROR",
                ascii_encode=False,
            )
            return values

    def _mad_filter(self, values, label):
        if not values:
            return values, 0.0, 0, 0
        arr = np.array(values)
        med = np.median(arr)
        mad = np.median(np.abs(arr - med))
        z = 0.6745 * (arr - med) / (mad + 1e-9)
        filtered = arr[np.abs(z) <= 3.5].tolist()

        safe_label = label.replace("-", "_")
        try:
            self.set_state(
                f"sensor.chatgpt_bed_{safe_label}_mad",
                state=round(mad, 2),
                attributes={
                    "unit_of_measurement": "raw",
                    "state_class": "measurement",
                },
            )
        except Exception as e:
            self.log(
                f"[mad_filter] Failed to set MAD sensor for {safe_label}: {e}",
                level="WARNING",
                ascii_encode=False,
            )
        try:
            self.set_state(
                f"sensor.chatgpt_bed_{safe_label}_filtered",
                state=len(filtered),
                attributes={
                    "original": len(arr),
                    "removed": len(arr) - len(filtered),
                    "unit_of_measurement": "samples",
                    "state_class": "measurement",
                },
            )
        except Exception as e:
            self.log(
                f"[mad_filter] Failed to set filtered-count sensor for {safe_label}: {e}",
                level="WARNING",
                ascii_encode=False,
            )

        return filtered, mad, len(arr), len(filtered)

    async def _update_threshold_from_history(self, kwargs):
        """Compute threshold entirely in raw ADC units."""
        self.occupied = self.get_state(self.occupancy_bool) == "on"
        if self.occupied:
            self.log(
                "⚠️ [thresh] Skipping threshold update—occupied or override",
                ascii_encode=False,
            )
            return
        self.log("🔍 [thresh] Calculating threshold (raw ADC units)", ascii_encode=False)

        manual_raw = None
        if self.input_threshold:
            state = self.get_state(self.input_threshold)
            try:
                manual_kg = float(state)
                manual_raw = manual_kg * self.scale
                self.log(
                    f"[thresh] Using manual threshold: {manual_kg:.2f}kg → {manual_raw:.2f} raw",
                    ascii_encode=False,
                )
            except Exception:
                manual_raw = None

        if manual_raw is not None:
            thr_raw = manual_raw
        else:
            raw_entity = (
                self.delta_sensor
                if self.delta_sensor.endswith("_raw")
                else f"{self.delta_sensor}_raw"
            )
            raw_entries = await self._get_history_chunked(raw_entity, days=14)

            occ_entries = await self._get_history_chunked(self.occupancy_bool, days=14)
            occ_states = {
                self.convert_utc(e["last_changed"]): e["state"] == "on"
                for e in occ_entries
                if "state" in e
            }

            def is_occupied(ts):
                nearest = max((t for t in occ_states if t <= ts), default=None)
                return occ_states.get(nearest, False)

            daily: dict = {}
            for e in raw_entries:
                try:
                    ts = self.convert_utc(e["last_changed"])
                    if is_occupied(ts):
                        continue
                    val = abs(float(e["state"]))
                    daily.setdefault(ts.date(), []).append(val)
                except Exception:
                    continue

            medians = []
            for day, vals in sorted(daily.items()):
                filtered, *_ = self._mad_filter(vals, f"thresh_raw_{day.isoformat()}")
                if filtered:
                    medians.append(statistics.median(filtered))
            if not medians:
                self.log("⚠️ [thresh] No valid samples, skipping", ascii_encode=False)
                return
            weights = [self.decay ** i for i in reversed(range(len(medians)))]
            thr_raw = float(np.average(medians, weights=weights))
            self.log(
                f"[thresh] Computed raw median threshold: {thr_raw:.2f}",
                ascii_encode=False,
            )

            min_thresh = float(self.args.get("min_threshold_raw", 6000.0))
            if thr_raw < min_thresh:
                self.log(
                    f"[thresh] Clamping threshold: {thr_raw:.2f} → {min_thresh:.2f}",
                    ascii_encode=False,
                )
                thr_raw = min_thresh

            thr_kg = thr_raw / self.scale
            self._set_paired_state(self.threshold_sensor, thr_raw, thr_kg)
            self.log(
                f"✅ [thresh] Updated threshold raw={thr_raw:.2f}, kg={thr_kg:.2f}",
                ascii_encode=False,
            )

    def _get_threshold(self):
        try:
            key = (
                self.threshold_sensor
                if self.threshold_sensor.endswith("_raw")
                else f"{self.threshold_sensor}_raw"
            )
            return float(self.get_state(key))
        except Exception:
            if self.input_threshold:
                try:
                    manual_kg = float(self.get_state(self.input_threshold))
                    return manual_kg * self.scale
                except Exception:
                    pass
            return float(self.args.get("default_threshold_raw", 500.0))

    def convert_utc(self, ts):
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return datetime.now()
        return ts

    def _update_hysteresis(self, kwargs):
        if not hasattr(self, "hysteresis_history"):
            self.hysteresis_history = []
        self.hysteresis_history.append(self.hysteresis_score)
        if len(self.hysteresis_history) > 10:
            self.hysteresis_history.pop(0)

        weights = [self.decay ** i for i in reversed(range(len(self.hysteresis_history)))]
        weighted_score = sum(
            s * w for s, w in zip(self.hysteresis_history, weights)
        ) / max(sum(weights), 1e-6)

        adjust = 0.05 * weighted_score
        old = getattr(self, "hysteresis", float(self.args.get("hysteresis", 50.0)))
        self.hysteresis = min(max(old + adjust, 5.0), 150.0)
        self.hysteresis_score = 0
        self.log(
            f"[hyst] Adjusted hysteresis to {self.hysteresis:.2f} raw (Δ={adjust:.2f}, score={weighted_score:.2f})",
            ascii_encode=False,
        )

        try:
            self.set_state(
                "sensor.chatgpt_bed_hysteresis_raw",
                state=round(self.hysteresis, 2),
                attributes={
                    "unit_of_measurement": "raw",
                    "state_class": "measurement",
                },
            )
        except Exception as e:
            self.log(
                f"[hyst] Failed to set hysteresis sensor: {e}",
                level="WARNING",
                ascii_encode=False,
            )

    async def _init_hysteresis(self):
        try:
            if self.delta_sensor.endswith("_raw"):
                hyst_entity = self.delta_sensor
            else:
                hyst_entity = f"{self.delta_sensor}_raw"
            entries = await self._get_history_chunked(hyst_entity, days=14)
            deltas = [
                abs(float(e.get("state")))
                for e in entries
                if e.get("state") not in (None, "unknown", "unavailable")
            ]
            _, mad, *_ = self._mad_filter(deltas, "init_hyst")
            self.hysteresis = min(
                mad * 1.5, float(self.args.get("hysteresis", 50.0))
            )
            self.log(
                f"[init] MAD-based hysteresis set to {self.hysteresis:.2f} raw",
                ascii_encode=False,
            )
        except Exception as e:
            self.log(
                f"[init] Fallback hysteresis=50.0 due to error: {e}",
                level="ERROR",
                ascii_encode=False,
            )
            self.hysteresis = float(self.args.get("hysteresis", 50.0))

    def _is_valid_state(self, state):
        return state not in (None, "unknown", "unavailable")

    async def _train_drift_model(self, kwargs):
        self.log("[drift] Training drift model", ascii_encode=False)
        try:
            history = await self._get_unoccupied_history(days=self.drift_train_days)
            if not history:
                self.log(
                    "[drift] No vacancy history available for drift model",
                    level="WARNING",
                    ascii_encode=False,
                )
                return

            x = []
            y = []

            for vacated_time, samples in history:
                if not samples:
                    continue
                baseline = samples[0][1]
                event_x = []
                event_y = []
                for ts, raw in samples:
                    elapsed = (ts - vacated_time).total_seconds()
                    if 0 < elapsed < self.drift_max_unoccupied_sec:
                        drift = raw - baseline
                        event_x.append(elapsed)
                        event_y.append(drift)
                if not event_x or max(event_y) - min(event_y) > 5000:
                    self.log(
                        f"[drift] Skipping event @ {vacated_time} — drift too wide or empty",
                        level="WARNING",
                        ascii_encode=False,
                    )
                    continue
                self.log(
                    f"[drift] Accepted event @ {vacated_time}: baseline={baseline:.2f}, first 3 drift: {[raw - baseline for _, raw in samples[:3]]}",
                    ascii_encode=False,
                )
                x.extend(event_x)
                y.extend(event_y)

            self.log(
                f"[drift] Final model training set: {len(x)} points from {len(history)} vacancy events",
                ascii_encode=False,
            )

            if len(x) >= 10:
                self.log(
                    f"[drift] Training points: N={len(x)}, Δt=[{min(x):.1f}, {max(x):.1f}], drift=[{min(y):.2f}, {max(y):.2f}]",
                    ascii_encode=False,
                )
                x_np = np.array(x)
                y_np = np.array(y)
                neg_mask = y_np < 0
                x_neg = x_np[neg_mask]
                y_neg = y_np[neg_mask]

                coeffs = np.polyfit(x_neg, y_neg, self.drift_model_order)
                self.drift_model_coeffs = coeffs
                self.log(f"[drift] Model coefficients: {coeffs}", ascii_encode=False)

                try:
                    import csv

                    drift_path = "/config/drift_model_data.csv"
                    with open(drift_path, "w", newline="") as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow(["elapsed_sec", "drift", "predicted"])
                        for xi, yi in zip(x_neg, y_neg):
                            ypi = np.polyval(coeffs, xi)
                            writer.writerow([xi, yi, ypi])
                    self.log(
                        f"[drift] Wrote model training data to {drift_path}",
                        ascii_encode=False,
                    )
                except Exception as e:
                    self.log(
                        f"[drift] Failed to write CSV: {e}",
                        level="WARNING",
                        ascii_encode=False,
                    )
            else:
                self.log(
                    "[drift] Insufficient data points to fit drift model",
                    level="WARNING",
                    ascii_encode=False,
                )
        except Exception as e:
            self.log(
                f"[drift] Failed to train model: {e}",
                level="ERROR",
                ascii_encode=False,
            )

    def _apply_drift_correction(self, raw_val):
        if self.last_vacated_time is None or self.drift_model_coeffs is None:
            return raw_val
        elapsed = (self.datetime() - self.last_vacated_time).total_seconds()
        if elapsed > self.drift_apply_max_sec:
            return raw_val
        try:
            drift = sum(
                [
                    c * (elapsed ** (len(self.drift_model_coeffs) - i - 1))
                    for i, c in enumerate(self.drift_model_coeffs)
                ]
            )
            if drift > 0:
                self.log(
                    "[drift] Positive Drift detected, setting drift to 0",
                    ascii_encode=False,
                )
                drift = 0
            corrected = raw_val - drift
            self.log(
                f"[drift] t={elapsed:.0f}s, est drift={drift:.2f}, corrected raw={corrected:.2f}",
                ascii_encode=False,
            )
            return corrected
        except Exception as e:
            self.log(
                f"[drift] Error applying model: {e}",
                level="ERROR",
                ascii_encode=False,
            )
            return raw_val

    async def _get_unoccupied_history(self, days):
        """Collect raw load cell samples for each vacancy event.

        Returns a list of (vacated_time, samples) where samples is a list of
        (timestamp, raw_value) tuples for up to drift_max_unoccupied_sec
        seconds after each OFF transition of the occupancy boolean.
        """

        raw_hist = await self._get_history_chunked(self.load_cell, days=days)
        occ_hist = await self._get_history_chunked(self.occupancy_bool, days=days)

        vacancy_events = []
        for i in range(1, len(occ_hist)):
            if occ_hist[i - 1]["state"] == "on" and occ_hist[i]["state"] == "off":
                t = self.convert_utc(occ_hist[i]["last_changed"])
                vacancy_events.append(t)

        history = []
        for vacated_time in vacancy_events:
            samples = []
            for r in raw_hist:
                ts = self.convert_utc(r["last_changed"])
                dt = (ts - vacated_time).total_seconds()
                if 0 <= dt <= self.drift_max_unoccupied_sec:
                    try:
                        val = float(r["state"])
                        samples.append((ts, val))
                    except Exception:
                        continue
            samples.sort()
            filtered_samples = []
            seen = set()
            for ts, val in samples:
                key = int((ts - vacated_time).total_seconds())
                if key not in seen:
                    filtered_samples.append((ts, val))
                    seen.add(key)
            samples = filtered_samples
            if samples:
                history.append((vacated_time, samples))

        return history


# EOF
