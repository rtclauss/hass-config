"""Deterministic MPC-lite thermostat preemptor.

Reads T+60 predictions from room_temp_predictor, and if any room is predicted
to overshoot the cooling setpoint by more than the configured margin, it
preemptively lowers the Ecobee cooling setpoint. A timer reverts the hold
after the estimated HVAC lead time elapses.

All rooms share one Ecobee, so the worst-case gap across all monitored rooms
drives a single set_temperature call.
"""

from datetime import datetime, timezone

import hassapi as hass

MONITORED_ROOMS = ["owner_suite", "office", "guest_room"]
MAX_SETPOINT_DROP_F = 3.0


class ThermalPreemptor(hass.Hass):
    def initialize(self):
        self.active_hold = None  # {'revert_handle': ..., 'started': datetime, 'reason': str}

        start = datetime.now(timezone.utc)
        import datetime as _dt
        start = start + _dt.timedelta(seconds=60)
        self.run_every(self._control_loop, start, 300)

    # ------------------------------------------------------------------
    # HVAC rate
    # ------------------------------------------------------------------

    def _hvac_rate_estimate(self):
        """Return |°F/min| cooling rate. Falls back to parametric formula when idle."""
        rate_state = self.get_state("sensor.ecobee_modeled_rate_deg_per_min")
        if rate_state not in (None, "unknown", "unavailable", ""):
            try:
                return abs(float(rate_state))
            except (TypeError, ValueError):
                pass
        # Parametric fallback replicating climate.yaml formula for cooling
        t_out_str = self.get_state("sensor.outside_temperature")
        try:
            t_out = float(t_out_str)
        except (TypeError, ValueError):
            t_out = 75.0
        return max(0.008, min(0.016, 0.028 - 0.00023 * t_out))

    # ------------------------------------------------------------------
    # Setpoint helpers
    # ------------------------------------------------------------------

    def _get_cooling_setpoint(self):
        t_high = self.get_state("climate.my_ecobee", attribute="target_temp_high")
        if t_high not in (None, "unknown", "unavailable"):
            try:
                return float(t_high)
            except (TypeError, ValueError):
                pass
        t_single = self.get_state("climate.my_ecobee", attribute="temperature")
        if t_single not in (None, "unknown", "unavailable"):
            try:
                return float(t_single)
            except (TypeError, ValueError):
                pass
        return 74.0

    @staticmethod
    def _safe_attr_float(value):
        if value in (None, "unknown", "unavailable", ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------

    def _control_loop(self, kwargs):
        if self.get_state("input_boolean.thermal_preemptor_enabled") != "on":
            return

        margin_str = self.get_state("input_number.thermal_preemptor_comfort_margin")
        try:
            margin = float(margin_str)
        except (TypeError, ValueError):
            margin = 0.5

        rate = self._hvac_rate_estimate()
        setpoint = self._get_cooling_setpoint()

        # Find worst-case predicted overshoot across all rooms
        worst_gap = 0.0
        worst_room = None

        for room in MONITORED_ROOMS:
            t60 = self._safe_attr_float(
                self.get_state(f"sensor.room_temp_prediction_{room}", attribute="t60")
            )
            if t60 is None:
                continue
            gap = t60 - setpoint
            if gap > worst_gap:
                worst_gap = gap
                worst_room = room

        if worst_gap < margin or worst_room is None:
            return

        if self.active_hold is not None:
            # Already preempting — don't stack another hold
            return

        # How many minutes does HVAC need to cool by worst_gap °F?
        lead_min = int(worst_gap / rate) + 5  # 5-min buffer

        new_setpoint = setpoint - worst_gap
        # Cap: never drop more than MAX_SETPOINT_DROP_F below scheduled
        new_setpoint = max(new_setpoint, setpoint - MAX_SETPOINT_DROP_F)

        self.call_service(
            "climate/set_temperature",
            entity_id="climate.my_ecobee",
            target_temp_high=round(new_setpoint, 1),
        )

        handle = self.run_in(self._revert, lead_min * 60, room=worst_room)
        self.active_hold = {
            "revert_handle": handle,
            "started": datetime.now(timezone.utc).isoformat(),
            "reason": worst_room,
            "gap": round(worst_gap, 2),
            "lead_min": lead_min,
            "new_setpoint": round(new_setpoint, 1),
        }
        self.log(
            f"Preempting for {worst_room}: predicted +{worst_gap:.1f}°F overshoot; "
            f"set T_high={new_setpoint:.1f}°F, revert in {lead_min}min"
        )

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def _revert(self, kwargs):
        room = kwargs.get("room", "unknown")
        self.call_service(
            "ecobee/resume_program",
            entity_id="climate.my_ecobee",
            resume_all=True,
        )
        self.active_hold = None
        self.log(f"Reverted preempt hold (triggered by {room} prediction)")
