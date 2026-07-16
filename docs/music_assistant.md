# Music Assistant & Sonos

Source of truth for Music Assistant (MA) / Sonos playback mechanics: entity
conventions, sync groups, Spotify URIs, volume, and re-onboard recovery.
Behavior (what plays when) is owned by `specs/alarm_wakeup.allium` and
`specs/night_routines.allium`; this doc covers the underlying MA/Sonos wiring.

## Entity conventions

- Sonos-backed Music Assistant players use an explicit `ma_<room>` entity ID,
  while their entity-registry `name` is the clean room name used by Home
  Assistant, HomeKit, and Siri:

  | Music Assistant entity ID | Entity-registry name |
  | --- | --- |
  | `media_player.ma_bedroom` | `Bedroom` |
  | `media_player.ma_bathroom` | `Bathroom` |
  | `media_player.ma_office` | `Office` |
  | `media_player.ma_den` | `Den` |
  | `media_player.ma_tiki_room` | `Tiki Room` |

  The `ma_` prefix makes integration ownership obvious in YAML and Developer
  Tools without leaking implementation detail into voice-control names.
- Bare `media_player.*_sonos` entities belong to Home Assistant's native Sonos
  integration and remain disabled. Do not target them from automations or
  scripts. AirPlay-only MA endpoints and `media_player.den_turntable` are
  separate players and are not aliases for the five room players above.
- Sync groups (MA Sonos sync-group players, renamed from MA defaults):
  - `media_player.ma_group_everywhere` — bedroom, bathroom, office, den, tiki
    (default whole-house target)
  - `media_player.ma_group_guest` — bedroom, bathroom (used when guest mode is on)
- Wake-up scripts intentionally do not inherit `ma_group_everywhere` membership.
  They dynamically prepare the exact wake group from MA `ma_<room>` players:
  bedroom + bathroom in guest mode, and bedroom + bathroom + office + den when
  guest mode is off. This keeps Tiki Room out of owner-suite wake-up audio even
  when the whole-house sync group includes it.

## NEVER hardcode a Spotify provider-instance id

MA's internal Spotify URIs look like `spotify--<instance>://playlist/<id>`
(e.g. `spotify--q7XNdM9r://...`). **`<instance>` changes whenever the Spotify
provider is re-added or MA re-onboards.** Do not pin it anywhere in config.

- Use the bare **`spotify:playlist:<id>`** form and let MA route to the live
  instance. `script.music_assistant_play_item` normalizes
  `spotify:user:<u>:playlist:<id>` → `spotify:playlist:<id>` and passes it through
  unpinned.
- History: a hardcoded `spotify--Tviw9k66` in `packages/media_player.yaml` went
  stale after a re-onboard (live instance became `spotify--q7XNdM9r`), so every
  Spotify bedtime/wake item resolved to **"No playable items found"** while the
  library still listed the playlists with full track art. The playlists were
  never dead — the instance id was. Fixed by de-pinning (PR #807, issue #802).
- A stale `spotify--<instance>` provider-mapping can linger in the MA **library
  DB** even when Settings → Providers shows only the new instance. It is harmless
  once nothing references it; a Spotify library re-sync scrubs it cosmetically.

## MA re-onboard recovery runbook

A re-onboard (new MA config entry) can, in one event:
1. **Purge the sync-group entities** (`ma_group_everywhere` / `ma_group_guest`).
2. **Drop the entity_id renames** (groups come back as `everywhere_sonos` /
   `guest_sonos`).
3. Leave the **Spotify library temporarily unsynced** — personal playlists
   resolve empty until the sync finishes (editorial + radio keep working).
4. **Change the Spotify provider-instance id** (see section above).

Recovery steps:
1. `homeassistant.reload_config_entry` on the MA entry → re-registers any sync
   group MA still has (returns under the **default** id `everywhere_sonos` /
   `guest_sonos`).
2. Recreate any group MA actually lost in the MA UI (Settings → Players → add
   group): Everywhere = the 5 speakers above; Guest = bedroom + bathroom.
3. Rename the groups back: `everywhere_sonos` → `ma_group_everywhere`,
   `guest_sonos` → `ma_group_guest`.
4. Restore each Sonos-backed room player's entity ID and entity-registry `name`
   from the table above. Entity-registry renames do not update YAML, so keep the
   IDs exact.
5. Let the Spotify library finish syncing; personal playlists self-heal.
6. Confirm no config pins a `spotify--<instance>` id — bare `spotify:` URIs only.

## Group volume

For group playback, set volume on the **individual member `ma_<room>` entities**, never
on the group entity. Proportional scaling rounds to 0 below ~8%.

## MA WebSocket API

The MA server WS API requires a Home Assistant auth token that is not exposed to
tooling (every command returns "Authentication required"), so **group creation
cannot be automated** — recreate groups in the MA web UI.
