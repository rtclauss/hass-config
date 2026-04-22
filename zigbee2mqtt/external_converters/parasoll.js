/**
 * IKEA PARASOLL (E2013) — patched external converter for Z2M 2.x
 *
 * Fixes two issues tracked in https://github.com/Koenkk/zigbee2mqtt/issues/22579:
 *  1. Battery drain: genPollCtrl cluster is intentionally excluded; the stock
 *     converter sets aggressive check-in intervals that drain the battery.
 *  2. Dropping off-network: explicitly binds the ssIasZone cluster so the
 *     device doesn't silently stop sending contact state changes after hours.
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
} = require("zigbee-herdsman-converters/lib/modernExtend");

module.exports = {
  zigbeeModel: ["PARASOLL Door/Window Sensor"],
  model: "E2013",
  vendor: "IKEA of Sweden",
  description: "PARASOLL door/window sensor (patched)",
  extend: [
    // Explicitly bind ssIasZone — the missing binding is the root cause of
    // sensors silently stopping state reports after a few hours.
    bindCluster({ cluster: "ssIasZone", clusterType: "input" }),
    iasZoneAlarm({
      zoneType: "contact",
      zoneAttributes: ["alarm_1"],
      // Required so configure sets up zoneStatus attribute reporting on ep2.
      // Without this, sensors that have never had the interval bounded will
      // silently oversleep at the factory default of 65000 s (~18 h) and drop
      // off the network. The blueprint automation then tightens max to 14400 s.
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
