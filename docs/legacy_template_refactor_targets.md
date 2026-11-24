# Legacy Template Refactor Targets

This note tracks the first-pass cleanup for issue #119 and the highest-value remaining legacy template patterns.

## Modernized in this pass

- `packages/tv.yaml`
  - Replaced the repeated basement TV power-on `wait_template` pattern with `script.wait_for_basement_media_player_ready`, which uses `wait_for_trigger` only when the player is still `off`.
  - Replaced the repeated Plex client availability `wait_template` with `script.wait_for_basement_plex_client_ready`, preserving the existing 10-second timeout.
- `packages/media_player.yaml`
  - Updated `script.play_video_games` to reuse the same basement media-player readiness helper.
- `packages/workday.yaml`
  - Replaced static `data_template` blocks in `script.wake_up_script` with standard `data`.
- `packages/zigbee_zwave.yaml`
  - Replaced representative `data_template` usage in the Inovelli day/night/reset scripts with standard `data`, keeping the existing templated entity expansion.

## Status (audited 2026-11-22)

- `data_template`: no live uses remain in `packages/` or `private_templates/`.
  The only matches are in commented-out legacy blocks (alerts, car, trips,
  curling, zone, light), which can be deleted rather than converted.
- `wait_template`: live uses remain in these sources:
  - `private_templates/xiaomi_robot_vacuum.yaml.tmpl` (11)
  - `private_templates/media_player.yaml.tmpl` (9)
  - `private_templates/trips.yaml.tmpl` (3)
  - `private_templates/zone.yaml.tmpl` (1)

  Before converting one to `wait_for_trigger`, check whether the wait has to
  pass straight through when the state is already true. `wait_for_trigger`
  only fires on a change, so that case needs a guard like the one the basement
  readiness helpers use.

## Next targets

1. The `wait_template` sites above, starting with the vacuum package.
2. `private_templates/trips.yaml.tmpl`, `private_templates/car.yaml.tmpl`, and `private_templates/weather.yaml.tmpl`
   - These files have the most `value_template`-driven branching and timing
     logic. Review them for native conditions, `choose`, helpers, or trigger IDs.

Private packages (`packages/{media_player,workday,trips,car,weather,...}.yaml`)
are rendered from `private_templates/*.tmpl`. Edit the template, not the
rendered package.

## Behavioral notes

- The new wait helper scripts preserve the prior "continue immediately if already ready" behavior and use a short re-check loop to avoid missing fast state transitions between the readiness check and trigger registration.
- The Plex wait still fails after 10 seconds if the client stays unavailable, matching the prior `continue_on_timeout: false` behavior.
