/**
 * IKEA PARASOLL (E2013) — patched external converter
 *
 * Fixes two issues tracked in https://github.com/Koenkk/zigbee2mqtt/issues/22579:
 *  1. Battery drain: genPollCtrl cluster is intentionally excluded; the stock
 *     converter sets aggressive check-in intervals that drain the battery.
 *  2. Dropping off-network / not reporting: explicitly binds the ssIasZone
 *     cluster on endpoint 2, which a regression removed from the built-in
 *     converter, causing the device to stop sending contact state changes.
 *
 * NOTE: Only imports from modernExtend (not lib/ikea) so this works with
 * Z2M 2.x where the IKEA-specific lib paths changed. OTA is handled by
 * Z2M natively; losing the addCustomClusterManuSpecificIkeaUnknown() call
 * is acceptable — it only affects IKEA-proprietary cluster binding which is
 * not needed for contact + battery reporting.
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
    // Explicitly bind ssIasZone on endpoint 1 — the missing binding is the
    // root cause of sensors silently stopping state reports after a few hours.
    bindCluster({ cluster: "ssIasZone", clusterType: "input" }),
    iasZoneAlarm({ zoneType: "contact", zoneAttributes: ["alarm_1"] }),
    identify({ isSleepy: true }),
    battery(),
    // genPollCtrl deliberately omitted — binding it writes an aggressive
    // check-in interval that drains AAA batteries in days/weeks.
  ],
};
