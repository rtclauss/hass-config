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
 * After installing this file:
 *   1. Restart Zigbee2MQTT (it will show "PARASOLL door/window sensor (patched)"
 *      in the device description once loaded correctly).
 *   2. Run the HA script "PARASOLL - Reconfigure All" to push the new config to
 *      every already-joined sensor.  Sensors that are completely unresponsive
 *      need a battery pull to wake them before reconfigure will reach them.
 */

const {
  deviceEndpoints,
  battery,
  identify,
  iasZoneAlarm,
  bindCluster,
} = require("zigbee-herdsman-converters/lib/modernExtend");

const {
  addCustomClusterManuSpecificIkeaUnknown,
  ikeaOta,
} = require("zigbee-herdsman-converters/lib/ikea");

const definition = {
  zigbeeModel: ["PARASOLL Door/Window Sensor"],
  model: "E2013",
  vendor: "IKEA of Sweden",
  description: "PARASOLL door/window sensor (patched)",
  extend: [
    addCustomClusterManuSpecificIkeaUnknown(),
    deviceEndpoints({ endpoints: { "1": 1, "2": 2 } }),
    // Explicitly bind ssIasZone — the missing binding is the root cause of
    // sensors silently stopping state reports after a few hours.
    bindCluster({ cluster: "ssIasZone", clusterType: "input", endpointNames: ["2"] }),
    iasZoneAlarm({ zoneType: "contact", zoneAttributes: ["alarm_1"] }),
    identify({ isSleepy: true }),
    battery(),
    ikeaOta(),
    // genPollCtrl is deliberately omitted — binding it causes Z2M to write an
    // aggressive check-in interval that drains the AAA battery in days/weeks.
  ],
};

module.exports = definition;
