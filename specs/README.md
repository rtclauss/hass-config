# Specs

These Allium files are the behavioral source of truth for configuration privacy, owner sleep/wake flows, lighting/media behavior, and Zigbee2MQTT lifecycle behavior in this repo.

- `alarm_wakeup.allium`: iOS alarm sync, timed wake-up branches, wake-up execution, bathroom follow-up audio, snooze/cancel, and morning recovery.
- `night_routines.allium`: bedtime prep, CPAP-triggered goodnight integrity, privacy-aware overnight shutdown, and bedtime exception handling.
- `z2m_lifecycle.allium`: Zigbee2MQTT join/leave/offline lifecycle handling, join-then-drop detection, systemic bridge-health escalation boundaries, and decommission reconciliation expectations.
- [`private_runtime_config.allium`](private_runtime_config.allium): private information and secret/template boundaries, synthetic public fixtures, safe rendering, and behavior-preserving configuration migrations. Publication and migration guarantees are maintainer obligations; renderer invariants are covered by executable tests. See [the operational guide](../docs/private_runtime_config.md) for deployment and rollback.

When configuration privacy, wake-up, alarm, bedtime, overnight, or Zigbee2MQTT lifecycle behavior changes, compare the implementation to the relevant `.allium` file before changing code. Do not update `.allium` definitions automatically; request owner approval for any spec change. If the implementation change is intentionally outside the spec or does not change governed behavior, document that as a classified gap in `specs/allium_weed_config.json` instead of editing the spec.
