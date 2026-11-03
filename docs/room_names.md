# Room Naming Model

Issue `#317` uses a single canonical key per room or space and keeps legacy live namespaces explicit instead of allowing ad hoc drift.

Rules:

- `docs/room_intent.yaml` remains the source of truth for behavior, privacy, and room-sensitive automation decisions.
- `scripts/room_name_registry.py` is the naming source of truth used by tests and automation-safe checks.
- Use the `Preferred UI Name` for new dashboards, helpers, script aliases, notifications, and friendly names.
- Do not mass-rename live entity IDs or Zigbee2MQTT `friendly_name` values just to match the preferred UI name. Open a separate safe-refactor issue first.
- If an existing live namespace is still required, add it to the registry instead of introducing a new alias.
- `Main Level` and `Upstairs` are existing Zigbee2MQTT floor prefixes for shared devices, not room names; the registry allows them without assigning room intent.

## Canonical Names

| Key | Preferred UI Name | HA Area | Live Namespace / Allowed Legacy Labels |
| --- | --- | --- | --- |
| `owner_suite_bedroom` | `Owner Suite Bedroom` | `Bedroom` | `Owner Suite`, `Master Bedroom`, `Bedroom` |
| `owner_suite_bathroom` | `Owner Suite Bathroom` | `Owner Suite Bathroom` | — |
| `guest_room` | `Guest Room` | `Guest Room` | `Guest Bedroom` |
| `guest_bathroom` | `Guest Bathroom` | `Guest Bathroom` | `Guest Bathroom` |
| `bathroom` | `Bathroom` | `Bathroom` | `Bathroom` |
| `office` | `Office` | `Office` | `Office` |
| `den` | `Den` | `Den` | `Den` |
| `dining_room` | `Dining Room` | `Dining Room` | `Dining Room`, `Living Room` |
| `laundry_room` | `Laundry Room` | `Laundry Room` | `Laundry`, `Laundry Room` |
| `kitchen` | `Kitchen` | `Kitchen` | `Kitchen` |
| `hallway` | `Hallway` | `Hallway` | `Hall` |
| `upstairs_hallway` | `Upstairs Hallway` | `Upstairs Hallway` | — |
| `main_foyer` | `Main Foyer` | `Main Foyer` | `Main Foyer` |
| `garage` | `Garage` | `Garage` | `Garage` |
| `deck` | `Deck` | `Deck` | `Deck` |
| `outside` | `Outside` | `Outside` | `Outside` |
| `powder_room` | `Powder Room` | `Powder Room` | `Powder Room` |
| `basement_great_room` | `Basement Great Room` | `Basement Great Room` | `Basement` |
| `unfinished_basement` | `Unfinished Basement` | `Unfinished Basement` | `Unfinished Basement` |
| `tiki_room` | `Tiki Room` | `Tiki Room` | `Tiki Room` |

## Enforcement

- `tests/test_room_name_registry.py` validates that `docs/room_intent.yaml`, Zigbee2MQTT room prefixes, and selected user-facing names stay inside the registry.
- GitHub Actions now runs `uv run --with pytest pytest`, so unexpected room-name drift fails in CI instead of waiting for a manual review.

## Zigbee2MQTT Device Naming

Pattern: `<Room namespace>/<Fixture> [N]`, with `Switch` appended for Inovelli wall switches and a plural noun for groups.

Stairway (Hall namespace):

| Z2M friendly name | Device | IEEE |
| --- | --- | --- |
| `Hall/Stairway` | Inovelli VZM31-SN switch (name predates the pattern; keep until a safe-refactor issue renames it) | `0xe0798dfffed2d17f` |
| `Hall/Stairway Bulbs` | Z2M group (switch endpoint 1 + all six bulbs) | — |
| `Hall/Stairway Bulb 1` | Hue filament ST19 (top of stairs) | `0x001788010bf70f29` |
| `Hall/Stairway Bulb 2` | Hue filament ST19 | `0x001788010bfa1470` |
| `Hall/Stairway Bulb 3` | Hue filament ST19 | `0x001788010bfa39d0` |
| `Hall/Stairway Bulb 4` | Hue filament ST23 | `0x001788010f83e730` |
| `Hall/Stairway Bulb 5` | Hue filament ST23 | `0x001788010f83f27b` |
| `Hall/Stairway Bulb 6` | Hue filament ST23 (bottom of stairs) | `0x001788010f83f38a` |

The bulb numbering follows the Z2M list order until each bulb is physically confirmed with Identify. The switch binds endpoint 2 to the group and joins it on endpoint 1; `reset_inovelli_switches` replays both.

Keep `select.hall_stairway_smartbulbmode` set to `Smart Bulb Mode` so the six Hue bulbs retain continuous power. Control their light output through Zigbee rather than cutting or dimming their mains supply. The reset script must preserve this setting; the switch's output mode remains `Dimmer`.

## Hallway and Stairway Adaptive Lighting

Adaptive Lighting owns individual bulbs, with each bulb assigned to exactly one profile:

| Profile | Light entities |
| --- | --- |
| Hallway | `light.hall_laundry`, `light.hall_main_foyer_1`, `light.hall_main_foyer_2`, `light.hall_upstairs_1`, `light.hall_upstairs_2`, `light.hall_transition` |
| Stairway | `light.hall_stairway_bulb_1` through `light.hall_stairway_bulb_6` |

Keep relay/switch entities and Zigbee2MQTT groups out of both profiles, and preserve the lack of overlap. A group's aggregate on state must not cause Adaptive Lighting to issue a group command that wakes its off members. These target lists are stored in the Adaptive Lighting integration's persisted UI options; update those options when changing ownership.

Turning on one bulb directly should adapt only that bulb and leave the other off bulbs off. Keep the Zigbee2MQTT groups and paddle bindings available for deliberate group commands. An explicit group, scene, or script command can still turn on every light it targets.

After changing profile options, verify:

- A direct single-bulb turn-on adapts that bulb while other off bulbs stay off.
- An explicit group or bound paddle command still controls its intended members.
- Lights stay off through at least two adaptation intervals and a scheduled controller reset.
- The profile light lists persist after the next normal Home Assistant restart.
