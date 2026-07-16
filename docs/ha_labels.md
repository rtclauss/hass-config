# Home Assistant Label Model

The repository owns both parts of the Home Assistant label configuration:

- `docs/ha_label_taxonomy.yaml` defines label IDs, display metadata, allowed scopes, and lifecycle.
- `docs/ha_label_assignments.json` defines explicit behavior/helper assignments, room-sensitive area assignments, matching rules for devices/entities, live-only drift, and retired-label migrations.

Labels express cross-cutting purpose: what an object affects or why it matters. Areas and floors remain the source of physical location, while categories remain table-specific UI organization.

## Model rules

- Keep active label IDs stable, lowercase, and snake case.
- Add a label beyond the initial taxonomy only when at least six objects need it and an existing label cannot express the concept accurately.
- Automations, scripts, scenes, and behavior-related helpers require explicit manifest entries and may have multiple labels.
- Ordinary devices and entities receive labels only when an explicit assignment or a meaningful domain, integration, manufacturer, area, or name rule matches.
- Do not rely on label inheritance. A label assigned to an area or device does not automatically become an entity label in every registry or template context, so the reconciler writes each intended assignment directly.
- Preserve labels outside the manifest's managed and retired sets. The reconciler owns only the labels named in those sets.
- Raw live exports contain household inventory and must remain local and uncommitted.

## Active domains

The 33 active labels cover privacy and behavioral context; wake-up and bedtime; presence; music and television; lighting, climate, openings, and security; cleaning, appliances, water, and energy; weather and travel; vehicles and aviation; notifications and deliveries; cameras and work; holidays and wildlife; maintenance and connectivity; sports and maker projects.

The complete names, descriptions, icons, colors, owners, reasons, and scopes live in the taxonomy file. The initial extensions above 30 are `device_connectivity`, `sports_recreation`, and `maker_projects`; live assignment audit must show at least six matching objects for each.

Room-sensitive area assignments are explicit and aligned with `docs/room_intent.yaml`:

- `guest_sensitive`: office, den, guest room, guest bathroom, and basement great room.
- `sleep_sensitive`: owner-suite bedroom/bathroom, office, den, guest room, and basement great room.
- `privacy_sensitive`: owner-suite bedroom/bathroom, office, den, guest room, and guest bathroom.
- `hallway`: hallway and upstairs hallway.

## Repository validation

Validate taxonomy, explicit coverage, stable scene IDs, matching rules, and the repository inventory:

```bash
python3 scripts/ha_label_taxonomy.py validate
```

Build the read-only behavior reference graph used to review multi-domain assignments:

```bash
python3 scripts/ha_label_taxonomy.py reference-graph
```

Run the focused tests:

```bash
uv run --with pytest pytest \
  tests/test_ha_label_taxonomy.py \
  tests/test_ha_label_assignments.py
```

## Live reconciliation

Set `HA_URL` and `HA_TOKEN` in the shell. Do not store credentials or live exports in the repository.

1. Export and retain a local backup:

   ```bash
   python3 scripts/ha_label_taxonomy.py export-live \
     --output /tmp/ha-label-live-before.json
   ```

2. Deploy the stable scene IDs and reload scenes so YAML scenes are registry-backed.
3. Preview, then create/update active definitions:

   ```bash
   python3 scripts/ha_label_taxonomy.py apply-labels
   python3 scripts/ha_label_taxonomy.py apply-labels --execute
   ```

4. Audit compiled assignments and runtime-only drift:

   ```bash
   python3 scripts/ha_label_taxonomy.py audit-assignments
   ```

   The audit fails when any desired area, device, or entity ID is absent from
   its live registry. `apply-assignments` uses the same guard and refuses to
   silently skip missing objects.

5. Preview and apply area, device, entity, automation, script, scene, and helper assignments:

   ```bash
   python3 scripts/ha_label_taxonomy.py apply-assignments
   python3 scripts/ha_label_taxonomy.py apply-assignments --execute
   ```

6. Re-export and verify that coverage is complete, extension thresholds pass, and retired assignments are zero.
7. Preview and remove retired definitions:

   ```bash
   python3 scripts/ha_label_taxonomy.py retire-labels
   python3 scripts/ha_label_taxonomy.py retire-labels --execute
   ```

`retire-labels --execute` refuses to delete anything while a retired label remains assigned. No reconciliation runs automatically at Home Assistant startup.

## Runtime drift policy

The manifest keeps the current 31 live-only automations and three live-only scripts labeled with `source: live_only`. Reconciliation never deletes them. They remain visible in audit output until their configuration is restored to the repository or intentionally removed through a separate reviewed change.
