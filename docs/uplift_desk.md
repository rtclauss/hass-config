# Uplift Desk

## Integration and migration

The active integration is upstream `Bennett-Wendorf/hass-uplift-desk` v2.0.0,
installed through HACS and using `uplift-ble==0.7.0`. It replaced the custom
fork v2.1.8 on 2026-09-28. Home Assistant sends commands through its Bluetooth
infrastructure; the active connection was verified through the office ESPHome
Bluetooth proxy. The older remote SSH/CLI scripts are not used by this package.

Before replacement, the installed custom component, desk package, integration
and entity/device registries, and HACS repository data were archived locally.
The archive is private and excluded from Git. Runtime addresses and backup
locations belong in local operational records, not committed configuration.

Keep the existing integration entry during migration. Preset 1, Preset 2,
Stop, and Height retain their unique IDs. HACS now tracks upstream instead of
the custom fork. The retired native max/min buttons can remain unavailable
in the registry; dashboards use the preserved manual script entities.

## Height configuration

The desk does not report its units or limits during setup. Its integration
options use `fallback_unit: inches` and `query_on_connect: true`.
Height reporting was physically verified at the minimum of 25.3 inches.

The max/min scripts use owner-confirmed targets, not the number entity's
generic 500-1300 mm fallback bounds:

| Control | Keypad target | Commanded target |
| --- | --- | --- |
| Minimum | 25.3 inches | 643 mm |
| Maximum | 50.9 inches | 1293 mm |

The maximum command was physically tested: the desk stopped at 50.8 inches,
which the owner accepted. The 50.9-inch target remains configured. Preset 1
and Preset 2 were also physically confirmed working after migration. Stop
and a commanded minimum move have not been physically tested in this migration.

`script.uplift_desk_move_to_limit` rejects invalid limit names, unavailable
entities, missing numeric bounds, and targets outside the number entity's
current bounds. An unknown setpoint is allowed because that is normal at rest.

## Automations and manual controls

`packages/desk.yaml` preserves Guest > Trip > Camera > other trigger priority.
Guest/trip activation requests maximum; camera activation recalls preset 2.
Departure, daily 18:00, and laptop inactivity for ten minutes request maximum.
Workday arrival recalls preset 1; the overnight reset runs Monday at 04:00.
Times follow Home Assistant's configured timezone. Inactivity is not proof
of sleep. Turning a mode off does not restore a position or replay missed moves.

Automated moves share a 45-second timer and single-running script. Commands
during that window are dropped, not queued. This is not physical motion
detection. Manual preset/max/min/Stop scripts bypass mode and timer checks;
manual movements do not start the automation timer.

## Validation and rollback

Run `uv run --with pytest --with pyyaml --with jinja2 pytest
tests/test_uplift_desk_native_component.py` and Home Assistant configuration
validation. Tests cover preserved dashboard routes, retired button references,
shared motion guard, both target conversions, invalid limits, unavailable
entities, missing bounds, and out-of-range targets. These are YAML/Jinja
behavior tests; Python line coverage does not measure HA action execution.

Rollback requires restoring the backed-up custom component and desk package
together, selecting the original fork in HACS, and restarting Home Assistant.
Restore only affected settings if needed; do not overwrite full registries
and discard unrelated changes. Preserve the existing desk config entry.
