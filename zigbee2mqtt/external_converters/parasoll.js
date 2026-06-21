/**
 * IKEA PARASOLL (E2013) — patched external converter for Z2M 2.x
 *
 * Addresses the issues tracked in https://github.com/Koenkk/zigbee2mqtt/issues/22579:
 *  1. Battery drain: genPollCtrl cluster is intentionally excluded; binding it
 *     writes an aggressive check-in interval. Most of the measured drain in the
 *     thread came from rejoin loops triggered by (2) below, so fixing (2) is the
 *     bigger lever.
 *  2. Stuck/dropped state: binds the ssIasZone cluster on endpoint 2 (a
 *     regression had removed it) so the device keeps sending contact-state
 *     changes, and sets zoneStatus min reporting to 0 so rapid open/close pairs
 *     are never dropped.
 *  3. Dropping off-network (the actual availability fix): the factory maximum
 *     reporting interval of 65000 s (~18 h) is longer than any sane availability
 *     timeout, so a healthy sleepy device gets marked offline. This converter
 *     cannot clamp that on its own — script.parasoll_enforce_intervals in
 *     packages/parasoll_fix.yaml clamps max to 14400 s (4 h) per device.
 *
 * Placement: /config/zigbee2mqtt/external_converters/parasoll.js
 * Z2M 2.x scans this folder automatically — no configuration.yaml entry needed.
 * Z2M symlinks node_modules into this folder so require() works correctly.
 */

const {
  iasZoneAlarm,
  battery,
  identify,
  bindCluster,
  deviceEndpoints,
} = require("zigbee-herdsman-converters/lib/modernExtend");

module.exports = {
  zigbeeModel: ["PARASOLL Door/Window Sensor"],
  model: "E2013",
  vendor: "IKEA of Sweden",
  description: "PARASOLL door/window sensor (patched)",
  extend: [
    // PARASOLL's ssIasZone cluster lives on endpoint 2, so the endpoint map
    // must be declared before bindCluster can target it by name.
    deviceEndpoints({ endpoints: { "1": 1, "2": 2 } }),
    // Explicitly bind ssIasZone on endpoint 2 — the missing binding (a
    // regression in herdsman-converters PR #7220) is the root cause of sensors
    // silently stopping state reports after a few hours. Without
    // endpointNames: ["2"] this binds the wrong (non-IAS) endpoint and is a
    // no-op; this mirrors the upstream stock E2013 definition.
    bindCluster({
      cluster: "ssIasZone",
      clusterType: "input",
      endpointNames: ["2"],
    }),
    iasZoneAlarm({
      zoneType: "contact",
      zoneAttributes: ["alarm_1"],
      // Sets up zoneStatus reporting on ep2 with min=0 (so rapid open/close
      // pairs are never dropped). NOTE: this also writes the factory max of
      // 65000 s (~18 h), which is longer than any sane availability timeout and
      // is what lets sensors get marked offline. The script.parasoll_enforce_intervals
      // automation (packages/parasoll_fix.yaml) then clamps max down to 14400 s.
      zoneStatusReporting: true,
    }),
    identify({ isSleepy: true }),
    battery({
      // Enable voltage so both batteryVoltage and batteryPercentageRemaining
      // are reported and visible in HA — matches what the stock IKEA converter
      // configures and ensures the blueprint can enforce intervals on both.
      voltage: true,
      voltageReporting: true,
    }),
    // genPollCtrl deliberately omitted — binding it writes an aggressive
    // check-in interval that drains AAA batteries in days/weeks.
  ],
};
