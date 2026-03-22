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

## Next targets

1. `packages/weather.yaml`
   - Several alert actions still use legacy `data_template`, and the alert automations also have template-heavy conditions that could move to more native condition blocks.
2. `packages/holidays.yaml`, `packages/curling.yaml`, and `custom_components/birdbuddy/blueprints/collect_postcard.yaml`
   - These still contain older `data_template` patterns that are mostly mechanical conversions.
3. `packages/trips.yaml`, `packages/car.yaml`, and `packages/weather.yaml`
   - These files contain the highest concentration of `value_template`-driven branching and timing logic that should be reviewed for native conditions, `choose`, helpers, or trigger IDs.

## Behavioral notes

- The new wait helper scripts preserve the prior "continue immediately if already ready" behavior by checking current state before waiting for a state change.
- The Plex wait still fails after 10 seconds if the client stays unavailable, matching the prior `continue_on_timeout: false` behavior.
