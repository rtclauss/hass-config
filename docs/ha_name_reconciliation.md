# Home Assistant Name Reconciliation

Issue `#1175` tracks the 2026.11 naming migration. Home Assistant now composes
display context from floors, areas, parent devices, devices, and entities. The
repository keeps canonical room identity in `scripts/room_name_registry.py` and
`docs/room_names.md`; the live registries remain the authority for integration
names, user overrides, device relationships, disabled entities, and diagnostic
entities.

## Read-only inventory

`scripts/ha_name_reconciliation.py` does not write to Home Assistant. It reads
the floor, area, device, and entity registries through supported WebSocket APIs.
The entity inventory includes disabled and hidden siblings, direct versus
device-inherited areas, parent devices, integration names, user overrides,
aliases, labels, config-entry ownership, and stable unique IDs.

Set a current read-only token in the shell, then create a private export:

```bash
HA_URL="https://home-assistant.example" HA_TOKEN="..." \
  python3 scripts/ha_name_reconciliation.py export-live \
  > .private-runtime-backup/ha-name-registry.json
```

The export contains private runtime metadata. Keep it under the gitignored
`.private-runtime-backup/` directory and never commit it, paste it into a PR, or
attach it to a public issue.

Create the reconciliation table as CSV:

```bash
python3 scripts/ha_name_reconciliation.py inventory \
  --live-json .private-runtime-backup/ha-name-registry.json \
  > .private-runtime-backup/ha-name-inventory.csv
```

Audit likely review groups without changing metadata:

```bash
python3 scripts/ha_name_reconciliation.py audit-live \
  --live-json .private-runtime-backup/ha-name-registry.json
```

Use `--summary-only` when recording aggregate validation evidence. It omits
entity, device, and area names while retaining counts for disabled/hidden
entities, child devices, missing context, overrides, and review groups.

## Interpreting findings

- `area_case_drift` is a case-only mismatch against the canonical HA area name.
- `area_name_drift` is a recognized preferred or legacy label that differs from
  the registry's current canonical HA area name. Reconcile the source of truth
  before changing live metadata.
- `areas_without_room_registry_match` needs an explicit registry/intent decision;
  it is not permission to invent a room mapping.
- `possible_main_entity_candidate` identifies an entity override equal to its
  device name. Inspect all device siblings before enabling the main-entity flag.
- `entity_override_repeats_device_name` is redundant under the 2026.11 model.
- `custom_entity_name_needs_context_review` may be intentional, but must be
  checked in room-local and whole-home surfaces before changing it.

The audit deliberately proposes no automatic rename. Before changing any live
name, inventory all sibling entities and consumers, preserve entity IDs and MQTT
topic identifiers, use the supported registry API, and verify dashboards,
notifications, voice aliases, helpers/groups, and restart persistence. Keep
runtime-only evidence and rollback data private.
