# Specs

These Allium files are the behavioral source of truth for the owner sleep/wake flows and Zigbee2MQTT lifecycle behavior in this repo.

- `alarm_wakeup.allium`: iOS alarm sync, timed wake-up branches, wake-up execution, bathroom follow-up audio, snooze/cancel, and morning recovery.
- `night_routines.allium`: bedtime prep, CPAP-triggered goodnight integrity, privacy-aware overnight shutdown, and bedtime exception handling.
- `z2m_lifecycle.allium`: Zigbee2MQTT join/leave/offline lifecycle handling, join-then-drop detection, systemic bridge-health escalation boundaries, and decommission reconciliation expectations.

When wake-up, alarm, bedtime, overnight, or Zigbee2MQTT lifecycle behavior changes, update the relevant `.allium` file in the same change.
