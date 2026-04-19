# Home Assistant Label Model

Issue `#511` defines the repo-owned canonical label taxonomy for Home Assistant. The source of truth is `docs/ha_label_taxonomy.yaml`; live labels should be reconciled from that file instead of being invented ad hoc in the UI.

## Model

- Use floors and areas for physical location. They answer where something is.
- Use labels for logical cross-cutting concerns. They answer why something matters or which behavior it can affect.
- Use categories for UI organization of automations, scripts, helpers, and scenes. They are not the behavioral taxonomy.
- Do not use labels as replacements for entity IDs, room names, Zigbee2MQTT namespaces, or the room naming registry.
- Do not rely on label inheritance. A label assigned to an area or device is useful for organization, but it does not automatically become an entity label in every registry and template context.

## Community Findings

- Home Assistant 2024.4 introduced floors, labels, and categories as different tools, not as competing names for the same thing.
- Community usage generally keeps areas physical and uses labels for logical sets such as "all lights", "debug/history", or "maintenance".
- A common pain point is assigning a label to a device but still needing explicit labels on selected entities for reliable searches, templates, and automation targets.

## Canonical Label Rules

- New labels must be added to `docs/ha_label_taxonomy.yaml` before they are created in live Home Assistant.
- Label IDs use lowercase snake_case and should not be renamed. Deprecate and replace instead.
- Each label needs a description, at least one scope, a lifecycle, an owner, and a reason.
- Unknown live labels are drift. Either add them to the taxonomy or remove them intentionally.
- Deprecated labels can remain in the taxonomy only with a replacement or a removal rationale.
- The current live `hallway` label is intentionally valid for the `hallway` and `upstairs_hallway` areas because both represent circulation space while remaining distinct HA areas.

## Reconciliation Workflow

Validate the repo taxonomy:

```bash
python3 scripts/ha_label_taxonomy.py validate
```

Create a read-only live export when `HA_URL` and `HA_TOKEN` are available:

```bash
HA_URL="https://home-assistant.example" HA_TOKEN="..." \
  python3 scripts/ha_label_taxonomy.py export-live
```

Audit live drift without changing Home Assistant:

```bash
python3 scripts/ha_label_taxonomy.py audit-live --live-json live-labels.json
```

Preview label definition reconciliation:

```bash
python3 scripts/ha_label_taxonomy.py apply-labels --live-json live-labels.json
```

Only after reviewing the dry-run output, apply label definition changes:

```bash
HA_URL="https://home-assistant.example" HA_TOKEN="..." \
  python3 scripts/ha_label_taxonomy.py apply-labels --execute
```

`apply-labels` creates and updates label definitions only. It never removes labels and never assigns labels to areas, devices, or entities. Assignment batches should be planned separately so room intent and privacy behavior remain reviewable.
