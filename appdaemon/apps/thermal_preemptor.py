"""Deterministic MPC-lite thermostat preemptor.

Reads T+60 room-temperature predictions from room_temp_predictor and, if any
monitored room is predicted to breach the Ecobee's active comfort setpoint by
more than the configured margin, preemptively nudges the setpoint so the HVAC
starts working ahead of the drift. A timer reverts to the Ecobee's own comfort
schedule (via ecobee.resume_program) after the estimated HVAC lead time.

The controller is mode-aware and works with the Ecobee's native comfort
settings rather than hard-coded temperatures:

  * cool       -> single `temperature` target; precool when rooms overshoot
  * heat       -> single `temperature` target; preheat when rooms undershoot
  * heat_cool  -> range; adjust `target_temp_high` (cool) or `target_temp_low`
                  (heat), whichever bound is predicted to be breached
  * off        -> do nothing

Preemption is skipped entirely while a window is open (configurable gate), so
the system never fights fresh air. All rooms share one Ecobee, so the
worst-case room drives a single set_temperature call.
"""

from datetime import datetime, timedelta, timezone

import hassapi as hass

MONITORED_ROOMS = ["owner_suite", "office", "guest_room"]
MAX_SETPOINT_SHIFT_F = 3.0  # never move the setpoint more than this from schedule
# Ecobee enforces a minimum spread between the heat and cool bounds (its
# "Heat/Cool Minimum Delta", 5°F out of the box) and rejects an inverted range
# outright. Overridable via the min_heat_cool_delta app arg.
MIN_HEAT_COOL_DELTA_F = 5.0


class ThermalPreemptor(hass.Hass):
    def initialize(self):
        self.active_hold = None  # {'revert_handle', 'started', 'reason', ...}

        self.climate_entity = self.args.get("climate_entity", "climate.my_ecobee")
        self.enable_switch = self.args.get(
            "enable_switch", "input_boolean.thermal_preemptor_enabled"
        )
        self.margin_number = self.args.get(
            "comfort_margin", "input_number.thermal_preemptor_comfort_margin"
        )
        # Open-window gate — preemption is skipped while this is `on`.
        self.window_gate = self.args.get("window_gate", "binary_sensor.any_window_open")
        self.rate_sensor = self.args.get(
            "rate_sensor", "sensor.ecobee_modeled_rate_deg_per_min"
        )
        self.outside_temp_sensor = self.args.get(
            "outside_temp_sensor", "sensor.canonical_outside_temperature"
        )
        self.min_heat_cool_delta = float(
            self.args.get("min_heat_cool_delta", MIN_HEAT_COOL_DELTA_F)
        )
        # Persisted hold state — survives an AppDaemon/HA restart so an in-flight
        # setpoint override is re-armed or resumed rather than orphaned.
        self.hold_active_switch = self.args.get(
            "hold_active_switch", "input_boolean.thermal_preemptor_hold_active"
        )
        self.hold_deadline_datetime = self.args.get(
            "hold_deadline_datetime", "input_datetime.thermal_preemptor_revert_at"
        )
        self.hold_reason_text = self.args.get(
            "hold_reason_text", "input_text.thermal_preemptor_hold_reason"
        )

        # Reconcile any hold left in the helpers before the loop can run, so the
        # re-entry guard sees it and cannot compound the override.
        self._reconcile_hold_on_start()

        start = datetime.now(timezone.utc) + timedelta(seconds=60)
        self.run_every(self._control_loop, start, 300)

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_attr_float(value):
        if value in (None, "unknown", "unavailable", ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _attr(self, name):
        return self._safe_attr_float(self.get_state(self.climate_entity, attribute=name))

    def _margin(self):
        m = self._safe_attr_float(self.get_state(self.margin_number))
        return m if m is not None else 0.5

    def _hvac_rate_estimate(self):
        """Return |°F/min| HVAC rate. Falls back to a parametric formula."""
        rate_state = self._safe_attr_float(self.get_state(self.rate_sensor))
        if rate_state is not None:
            return abs(rate_state)
        # Parametric fallback replicating the climate.yaml cooling formula.
        t_out = self._safe_attr_float(self.get_state(self.outside_temp_sensor))
        if t_out is None:
            t_out = 75.0
        return max(0.008, min(0.016, 0.028 - 0.00023 * t_out))

    def _worst_breach(self, setpoint, cooling):
        """Largest predicted breach of `setpoint` across monitored rooms.

        cooling=True  -> breach is t60 above setpoint (overshoot).
        cooling=False -> breach is t60 below setpoint (undershoot).
        Returns (gap_degrees, room) with gap >= 0.
        """
        worst_gap = 0.0
        worst_room = None
        for room in MONITORED_ROOMS:
            t60 = self._safe_attr_float(
                self.get_state(f"sensor.room_temp_prediction_{room}", attribute="t60")
            )
            if t60 is None:
                continue
            gap = (t60 - setpoint) if cooling else (setpoint - t60)
            if gap > worst_gap:
                worst_gap = gap
                worst_room = room
        return worst_gap, worst_room

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------

    def _control_loop(self, kwargs):
        if self.get_state(self.enable_switch) != "on":
            return
        if self.active_hold is not None:
            # Already preempting — let the revert timer clear it.
            return
        if self.get_state(self.window_gate) == "on":
            return

        mode = self.get_state(self.climate_entity)
        if mode in (None, "off", "unavailable", "unknown"):
            return

        margin = self._margin()

        # Resolve which bound(s) to defend based on the active mode, and pick
        # the single most-breached candidate (all rooms share one Ecobee).
        candidates = []  # (gap, room, cooling, setpoint, temp_field)
        if mode == "cool":
            sp = self._attr("temperature")
            if sp is not None:
                gap, room = self._worst_breach(sp, cooling=True)
                candidates.append((gap, room, True, sp, "temperature"))
        elif mode == "heat":
            sp = self._attr("temperature")
            if sp is not None:
                gap, room = self._worst_breach(sp, cooling=False)
                candidates.append((gap, room, False, sp, "temperature"))
        elif mode == "heat_cool":
            cool_sp = self._attr("target_temp_high")
            heat_sp = self._attr("target_temp_low")
            if cool_sp is not None:
                gap, room = self._worst_breach(cool_sp, cooling=True)
                candidates.append((gap, room, True, cool_sp, "target_temp_high"))
            if heat_sp is not None:
                gap, room = self._worst_breach(heat_sp, cooling=False)
                candidates.append((gap, room, False, heat_sp, "target_temp_low"))

        candidates = [c for c in candidates if c[1] is not None]
        if not candidates:
            return
        gap, room, cooling, setpoint, temp_field = max(candidates, key=lambda c: c[0])
        if gap < margin:
            return

        rate = self._hvac_rate_estimate()
        lead_min = int(gap / rate) + 5 if rate > 0 else 15  # +5min buffer

        # Nudge toward the breach, capped at MAX_SETPOINT_SHIFT_F from schedule.
        shift = min(gap, MAX_SETPOINT_SHIFT_F)
        new_setpoint = round(setpoint - shift if cooling else setpoint + shift, 1)

        data = {"entity_id": self.climate_entity}
        if temp_field == "temperature":
            data["temperature"] = new_setpoint
        else:
            # heat_cool range mode requires BOTH bounds on every call; move the
            # breached bound and keep the other at its scheduled value. The moved
            # bound must not cross or crowd the opposite one: nudging a 68-70
            # range by the full 3°F shift would ask for high=67 against low=68,
            # an inverted range the thermostat rejects. Clamp to the minimum
            # delta, and skip the call entirely when that leaves no headroom —
            # there is no way to preempt without fighting the other bound.
            cool_sp = self._attr("target_temp_high")
            heat_sp = self._attr("target_temp_low")
            if cool_sp is None or heat_sp is None:
                return
            if temp_field == "target_temp_high":
                new_setpoint = round(max(new_setpoint, heat_sp + self.min_heat_cool_delta), 1)
                if new_setpoint >= cool_sp:
                    return
            else:
                new_setpoint = round(min(new_setpoint, cool_sp - self.min_heat_cool_delta), 1)
                if new_setpoint <= heat_sp:
                    return
            data["target_temp_high"] = new_setpoint if temp_field == "target_temp_high" else cool_sp
            data["target_temp_low"] = new_setpoint if temp_field == "target_temp_low" else heat_sp

        self.call_service("climate/set_temperature", **data)

        revert_at = datetime.now(timezone.utc) + timedelta(minutes=lead_min)
        handle = self.run_in(self._revert, lead_min * 60, room=room)
        self.active_hold = {
            "revert_handle": handle,
            "started": datetime.now(timezone.utc).isoformat(),
            "revert_at": revert_at.isoformat(),
            "reason": room,
            "mode": mode,
            "direction": "cool" if cooling else "heat",
            "gap": round(gap, 2),
            "lead_min": lead_min,
            "new_setpoint": new_setpoint,
        }
        self._persist_hold(revert_at, room)
        self.log(
            f"Preempting {'cool' if cooling else 'heat'} for {room} ({mode}): "
            f"predicted {gap:.1f}°F breach; set {temp_field}={new_setpoint}°F, "
            f"revert in {lead_min}min"
        )

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def _revert(self, kwargs):
        room = kwargs.get("room", "unknown")
        self.call_service(
            "ecobee/resume_program",
            entity_id=self.climate_entity,
            resume_all=True,
        )
        self.active_hold = None
        self._clear_persisted_hold()
        self.log(f"Reverted preempt hold to comfort schedule (was driven by {room})")

    # ------------------------------------------------------------------
    # Persistence — the hold outlives an AppDaemon/HA restart
    # ------------------------------------------------------------------

    def _persist_hold(self, revert_at, reason):
        """Mirror the active hold into helpers so a restart can recover it."""
        self.call_service(
            "input_datetime/set_datetime",
            entity_id=self.hold_deadline_datetime,
            timestamp=revert_at.timestamp(),
        )
        self.call_service(
            "input_text/set_value",
            entity_id=self.hold_reason_text,
            value=str(reason)[:120],
        )
        # Set the active flag last: a reader that sees it on can trust that the
        # deadline and reason are already written.
        self.call_service("input_boolean/turn_on", entity_id=self.hold_active_switch)

    def _clear_persisted_hold(self):
        self.call_service("input_boolean/turn_off", entity_id=self.hold_active_switch)

    def _reconcile_hold_on_start(self):
        """Recover a hold the helpers say was active when the app last stopped.

        Without this, a reload drops self.active_hold and the revert timer while
        the thermostat keeps the shifted setpoint — and the now-clear re-entry
        guard lets the next loop shift again from the already-shifted value.
        """
        if self.get_state(self.hold_active_switch) != "on":
            return

        deadline_ts = self._safe_attr_float(
            self.get_state(self.hold_deadline_datetime, attribute="timestamp")
        )
        reason = self.get_state(self.hold_reason_text) or "unknown"
        now_ts = datetime.now(timezone.utc).timestamp()

        if deadline_ts is None or deadline_ts <= now_ts:
            # Deadline already passed (or unreadable) while the daemon was down —
            # resume the schedule now rather than leave the override in place.
            self.call_service(
                "ecobee/resume_program",
                entity_id=self.climate_entity,
                resume_all=True,
            )
            self._clear_persisted_hold()
            self.log(
                f"Resumed comfort schedule on start: hold for {reason} had "
                "already expired while the app was stopped."
            )
            return

        remaining = int(deadline_ts - now_ts)
        handle = self.run_in(self._revert, remaining, room=reason)
        self.active_hold = {
            "revert_handle": handle,
            "started": None,
            "revert_at": datetime.fromtimestamp(deadline_ts, timezone.utc).isoformat(),
            "reason": reason,
            "recovered": True,
        }
        self.log(
            f"Recovered in-flight preempt hold for {reason}; reverting in "
            f"{remaining // 60}min."
        )
