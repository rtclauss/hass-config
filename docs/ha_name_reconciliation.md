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
- `dangling_area_references` lists devices and entities whose `area_id` points
  at a deleted area. Home Assistant raises an error in `area_id()` and
  `area_name()` for them, and area targets and Assist area commands skip them.
  Re-map each one only after confirming which room it belongs to.

## Rename-safe consumers

Display names are not identifiers. Config that needs a stable value must read
one that a Home Assistant rename cannot change:

- Zigbee2MQTT topics use `device_attr(entity_id, 'name')`, the
  integration-supplied device name, which equals the Zigbee2MQTT
  `friendly_name`. A UI device rename writes `name_by_user` instead. Never build
  a topic from `friendly_name` or `device_name()`.
- Bermuda area/floor sensors report the area *name* as their state. Room logic
  compares their `area_id` / `floor_id` attributes instead.
- `friendly_name` is kept only for compatibility in 2026.11 and is planned for
  deprecation. Use `entity_name()`, `device_name()` and `area_name()` for
  display text; `tests/test_ha_2026_11_entity_names.py` rejects new reads.

## 2026.11 registry behavior

- An entity whose custom name equals its device name now composes a doubled
  `friendly_name` (for example `Dining Room Dining Room`). That doubled name
  also reaches Assist and the logbook. Clear the override so the entity
  inherits the device name.
- An entity without a name of its own cannot keep an area of its own. Clear
  the entity area in the same update (the device area then applies), and when
  rolling back, restore the name before the area.

## Batch log

### Batch 1 (2026-11-08, Core 2026.11.0)

Display metadata only. Entity IDs, unique IDs, Zigbee2MQTT names, aliases,
labels, and voice exposure were unchanged; the before/after registry diff
contained exactly the changes below.

- Areas aligned to `scripts/room_name_registry.py`: `dining_room`,
  `guest_bathroom`, `guest_room`, `upstairs_hallway` (case only).
- Registry aligned to live HA: `owner_suite_bedroom` uses the existing
  `Owner Suite Bedroom` area (`bedroom`); `basement_bathroom` added as a
  naming-only entry pending a room-intent decision.
- Redundant overrides cleared (doubled names fixed): `light.dining_room_all`,
  `light.dining_room_lamps`, `light.office_floor_lamp`,
  `light.office_floor_lamp_1`, `light.office_floor_lamp_2`,
  `media_player.living_room_3`, `media_player.dining_room_dining_room`,
  `remote.dining_room_dining_room`. Their entity areas matched the device area
  or pointed at a deleted area; they now inherit the device area.
- `light.office_ceiling`: dangling entity area cleared; custom name kept.
- Room confidence now scores by Bermuda area/floor IDs. This also fixes the
  owner-suite bedroom phone/watch signal, which never matched after the area
  was renamed to `Owner Suite Bedroom`.

Verified: configuration check valid; names, areas, and all 35 Inovelli LED
topics rendered as expected; no new log errors. Rollback map and before/after
exports are stored privately under `.private-runtime-backup/`.

### Batch 2 (2026-11-08): dangling area references

33 of the 34 dangling references were re-mapped with owner confirmation. Only
area assignments changed; the before/after diff showed no other field changes
and no added or removed entity IDs.

The old IDs were identified from a 2022 automation that listed its target
areas alphabetically by name. Each ID's position between known areas, plus its
devices' names, identified the deleted area:

| Deleted area | Re-mapped to |
| --- | --- |
| Office | Office: `light.office_all`, `light.office_lava_lamp` |
| Kitchen | Kitchen: North/South Kitchen panels, Rubber Plant sensor |
| Living Room | Dining Room: the `living room` device, N/S Nepenthes sensors |
| `owner_suite_bathroom` (old ID) | Owner Suite Bathroom (`bathroom`): Elkhorn Fern, Sansevieria sensors |
| Basement | Basement Great Room: LG TV, `script.watch_*`, `light.all_basement_lights` |
| Basement | Unfinished Basement: OctoPrint (2), watermeter, sump-pump level, USW Pro 24 PoE |
| Outdoor area | Outside: Rachio (2), front-door smart motion sensor |
| Outdoor area / unknown | No area: Tomorrow.io weather service, Monstera sensor |

Effects: `area_name()` works for every moved entry, and `sensor.last_motion_area`
no longer errors when the front-door motion sensor triggers. The Unfinished
Basement leak trigger still matches only its moisture sensor; none of the moved
devices has a moisture binary sensor.

The last reference, `input_boolean.front_door_lock` (deleted `front_door`
area), moved to **Hallway**, alongside the front door contact sensor
(`Main Foyer/Front Door` device) at the owner's request. Its only consumer, the
template `lock.front_door_lock`, targets it by entity ID. The audit now reports
zero dangling references, zero area drift, and no unmatched areas.

A Main Foyer area was briefly created and then deleted, with owner
confirmation, once it was left empty. The registry's `main_foyer` entry still
names a `Main Foyer` HA area that does not exist live; the foyer's devices
(front door contact, foyer motion, foyer lights) remain in Hallway. Creating
that area and moving them into it would change Hallway area views and Assist
commands, so it needs its own reviewed batch.

### Batch 4 (2026-11-08): Bond ceiling fans and lights

Goal: voice assistants never hear the same name for the fan and the light of
one fixture. Before this batch, `light.den_ceiling` and `fan.den_ceiling` were
both "Den Ceiling Fan", both Guest Room entities carried the alias "Guest Room
Ceiling", and `fan.owner_suite` was named and aliased "Owner Suite", which is
also an area alias.

| Device (was) | Device (now) | Fan entity | Light entity |
| --- | --- | --- | --- |
| Den Fan | Den Ceiling | Fan → Den Ceiling Fan | Light → Den Ceiling Light |
| Office Fan | Office Ceiling | Fan → Office Ceiling Fan | Light → Office Ceiling Light |
| Guest Room Fan | Guest Room Ceiling | Fan → Guest Room Ceiling Fan | Light → Guest Room Ceiling Light |
| Owner Suite Fan | Owner Suite Ceiling | Fan → Owner Suite Ceiling Fan | Light → Owner Suite Ceiling Light |

- The device name keeps the room on purpose: Alexa receives only the friendly
  name, with no area context, so four "Ceiling Light" entities would collide.
  This is a justified exception to "do not repeat the area in device names".
- Every entity has its own-name alias on, plus an explicit full-name alias.
  Colliding aliases were dropped; unique legacy aliases were kept ("Ceiling
  Light", "Guest Ceiling Light", "Owner Suite Ceiling").
- The `light.guest_room_ceiling` customize `friendly_name` ("Guest Ceiling
  Light") is removed in the repository; until that deploys, its friendly name
  stays "Guest Ceiling Light", which is unique and says Light.
- `tests/test_bond_fan_light_names.py` pins unique Fan/Light spoken names and
  rejects customize names on these entities.
- The sibling Bond buttons (for example "Guest Room Ceiling Ceiling fan 3 Start
  Dimmer") keep the integration's doubled names; they are not exposed to voice.

**Siri** reads the HomeKit Bridge accessory names, which HomeKit caches at
pairing. HA renames do not reach them. `homekit.reset_accessory` would pick up
the new names, but Apple Home then treats the accessory as new and its room,
scenes, and automations must be restored. Renaming in the Home app keeps them.
`light.den_ceiling` is not included in the HomeKit Bridge.

### Batch 5 (prepared): window contacts

Code (this PR): `custom_templates/display_name.jinja` composes whole-home names
(area + device + entity, without repeating context). The egress list and the
open-window list use it, and the 19 window-contact customize `friendly_name`
overrides are removed. The egress change also fixes the blank names that doors
already produce in 2026.11, because door contacts are main entities and
`entity_name()` returns an empty string for them.

Live rename, to apply **after** this code deploys (otherwise the deployed
egress list would show blank window names): for each contact, set the device
name to the fixture without the room (`Kitchen/North Window` → `North Window`;
the area supplies `Kitchen`), make the contact the device's main entity, and add
its old full name as an alias. Zigbee2MQTT friendly names and MQTT topics are
untouched; window contacts are not in the HomeKit Bridge.

### 2026.11 naming rule learned here

Names written after the 2026.11 upgrade are stored as the entity's own part
and are composed after the device name ("Den Fan" + "Den Ceiling Light" became
"Den Fan Den Ceiling Light"). Names carried over from before the upgrade are
shown as written. Design new names as `<device>` + `<entity>` pairs, and expect
a rollback that restores a legacy full name to be composed too.

Remaining: Music Assistant room players (deliberate, contract-tested),
Adaptive Lighting Dining Room switches, and the one-off overrides.

The audit deliberately proposes no automatic rename. Before changing any live
name, inventory all sibling entities and consumers, preserve entity IDs and MQTT
topic identifiers, use the supported registry API, and verify dashboards,
notifications, voice aliases, helpers/groups, and restart persistence. Keep
runtime-only evidence and rollback data private.
