# Smart Cat (cat insights for the Litter-Robots)

Smart Cat is a custom integration (`smartcat`) that recreates the useful parts
of Whisker+ locally: per-cat visits, visit duration, a time-of-visit pattern,
multi-year history, outlier and trend detection, and forecasts for when each
Litter-Robot's waste drawer fills and its litter needs topping up. It is
written for this house, so unlike the HACS integrations it is tracked here
(#1248, see [custom_components.md](custom_components.md)):

- `custom_components/smartcat/`: the integration. `core/` is plain Python
  (parsing, cat identification, analytics, forecasts, SQLite store) with no
  Home Assistant imports; the rest is the HA glue.
- `packages/smartcat.yaml`: notifications.
- `lovelace/dashboards/cats.yaml`: the Cats dashboard.
- `tests/test_smartcat_core.py`, `tests/test_smartcat_package.py`: run in the
  normal suite.
- `tests/smartcat_ha/`: Home Assistant integration tests with fake robots (see
  [Validation](#validation-and-rollback)).

Smart Cat is not a diagnostic tool and does not replace veterinary care.

## How it works

- **No extra login.** Smart Cat borrows the session of the core Whisker
  (`litterrobot`) integration.
- **Visits.** Main Level (LR4): rebuilt from the activity feed (cat detected,
  weight recorded, clean cycle); the cat left at cycle start minus the
  clean-cycle wait time, which gives the duration. Basement (LR5): native
  `PET_VISIT` records.
- **Which cat.** Each cat learns a robust weight band (median/MAD) per robot.
  Partial weigh-ins are attributed to the cat but never learned from and never
  count as its weight (sensors, trend, alerts, statistics), even on a pet-id
  visit. The band follows gradual change, so real weight loss still counts.
  LR5 pet ids are used when present.
- **A second cat.** Weigh-ins no cat explains are pooled; a tight, persistent
  group outside every band, or one that appeared suddenly, turns on
  `binary_sensor.smart_cat_new_cat_suspected`.
- **Insights.** Today vs. a 28-day baseline, 30-day time-of-day histogram,
  7-day weight median, Theil-Sen weight trend, 30-day weight change. Trend and
  change are measured within each robot and then combined, so a cat moving
  from Main Level to the Basement is not a 2 lb "loss".
- **Forecasts.** Per-cycle drawer/litter rate within the current fill period
  (reset when the drawer is emptied or litter added) times recent cycles per
  day; falls back to earlier periods, then level vs. time.

Actions: `smartcat.add_cat` (`name`, optional `weight_lbs`, `active_from`),
`smartcat.rename_cat`, `smartcat.remove_cat` (a cat imported from a Whisker pet
profile stays removed until added again by name), `smartcat.backfill` (`days`),
`smartcat.get_visits` (returns visits). Events: `smartcat_visit` per new visit
and `smartcat_new_cat_suspected`.

## Install

1. Pull the change onto the host (see [Deploy](#deploy)), then restart.
2. Settings → Devices & services → Add integration → **Smart Cat**. The core
   **Whisker** integration must already be set up: Smart Cat reuses its login,
   so no credentials are entered.
3. Options: waste drawer full at 80%, litter refill at 70% (the same thresholds
   as the `litter_robot` reminders), backfill 1460 days, retention 0 (forever).

On first start Smart Cat fetches the last 30 days, then backfills older
history about six months per 5-minute refresh. The
`sensor.smart_cat_unassigned_visits_7_days` attribute `backfill_complete`
shows when it is done. History lives in `/config/smartcat.db`, separate from the
recorder's 90-day purge, and is also published as long-term statistics
(`smartcat:<cat>_visits`, `smartcat:<cat>_weight`,
`smartcat:<cat>_visit_duration`).

## Entity contract

Cats come from the Whisker pet profiles; today that is Splashy (`splashy`).

| Entity | Meaning |
| --- | --- |
| `sensor.splashy_insight` | `normal`, `insufficient_data` (first week), or the most important change; `summary` attribute is a one-line daily summary |
| `binary_sensor.splashy_needs_attention` | On while any change is active; `kinds` and `messages` attributes |
| `sensor.splashy_daily_visits` | Visits today; `daily_counts` (14 d), `hourly_histogram_30d`, `baseline_mean` |
| `sensor.splashy_last_visit`, `_last_visit_duration`, `_average_visit_duration` | Visit timing |
| `sensor.splashy_typical_weight`, `sensor.splashy_weight_trend` | 7-day median of trusted weigh-ins; Theil-Sen lb/week |
| `sensor.<robot>_waste_drawer_full_forecast`, `_litter_refill_forecast` | Timestamps; attributes hold rate per cycle, cycles/day, days remaining, method |
| `sensor.<robot>_cycles_per_day`, `sensor.<robot>_visits_today` | Robot activity (on the existing Litter-Robot devices) |

Robot entities attach to the core integration's device entry itself. Device
identifiers are scoped per config entry since HA 2026.10, so identifier-only
device info would instead create a second device named "Smart Cat" and give
the entities `sensor.smart_cat_*` ids.
| `binary_sensor.smart_cat_new_cat_suspected` | Weigh-ins that match no known cat |

The core Whisker integration already owns `sensor.splashy_weight` (last raw
weigh-in) and `sensor.splashy_visits_today` for each pet profile, so Smart
Cat's sensors are named "Typical weight" and "Daily visits" to avoid taking
`_2` entity ids.

Observed while building it: the Main Level robot weighs Splashy about 2 lb
heavier than the Basement one (≈13.1 vs ≈11 lb), and partial weigh-ins (paw on
the step) read 6.5–9.7 lb. Smart Cat learns a weight band per robot and never
learns from partial weigh-ins, so neither looks like a second cat.

## Notifications

Per the [notification policy](notification_policy.md):

- **Check on the cat**: pushes when `binary_sensor.<cat>_needs_attention`
  gains a kind of change it did not have (for example `frequency_high`,
  `no_recent_visits`, `weight_loss`). Changed numbers, reordering, or one of two
  changes resolving do not re-alert. Back to normal removes the notification
  by tag (`smartcat_attention_<cat>`) without a new push.
- **New cat**: pushes when `binary_sensor.smart_cat_new_cat_suspected` turns on.
  Run the `smartcat.add_cat` action with just a name: it adopts the suspected
  weight and arrival time, so earlier history stays with the existing cat.
  The notification clears by tag (`smartcat_new_cat`).
- Transitions from or to `unavailable`/`unknown` (startup, integration reload)
  never push.
- If no robot's activity can be fetched, the update fails and the entities go
  unavailable. If only one robot cannot be fetched for 30 minutes, "fewer
  visits" changes (`no_recent_visits`, `frequency_low`) are held back, since
  the cat may be using that robot; `stale_robots` on the coordinator data
  names it.
- Forecasts are dashboard-only. The `litter_robot` package still owns the
  replace-bag and add-litter tasks.

## Adding a cat

A new Whisker pet profile is imported on the next refresh, and Smart Cat
reloads itself to add the cat's entities. After that or `smartcat.add_cat`, add `binary_sensor.<cat>_needs_attention` to the
trigger list of `smartcat_cat_needs_attention`, copy the Splashy section of
the Cats dashboard, and extend `tests/test_smartcat_package.py`.

## Deploy

The host checkout at `/config` picks up `custom_components/smartcat/` with the
normal pull. Use the backup-pull-restore steps in
[custom_components.md](custom_components.md#deploy-warning-read-before-pulling-this-change-onto-a-host)
so HACS-modified files do not block it, then restart Home Assistant (a new
integration needs a restart, not a reload) and add Smart Cat. Code changes
later need a restart too.

## Validation and rollback

Run `uv run --with pytest pytest`. `tests/test_smartcat_core.py` covers
parsing, identification (including Splashy's real weigh-ins, the per-robot
offset, partial weigh-ins and a second cat appearing), analytics, forecasts
and the store. `tests/test_smartcat_package.py` covers the push decision matrix
(new, added, replaced, drifted, reordered, partially resolved, recovered),
startup/reload suppression, tag-based clearing, link rendering, and dashboard
registration.

The integration tests in `tests/smartcat_ha/` need Home Assistant's test
harness, which disables sockets for every test it loads, so the main suite
skips them and CI runs them in the `Smart Cat integration tests` job:

```sh
uv run --no-project --python 3.14.10 \
  --with pytest-homeassistant-custom-component==0.13.375 --with pylitterbot==2025.6.5 \
  pytest -o asyncio_mode=auto -p no:cacheprovider tests/smartcat_ha
```

Use Python 3.14.4 or newer: 3.14.3's `unittest.mock` cannot autospec the
recorder. Bump the plugin with the HA version in the config-check job.

Rollback: delete the Smart Cat integration entry, remove
`packages/smartcat.yaml`, the `db-cats` dashboard entry,
`lovelace/dashboards/cats.yaml` and `custom_components/smartcat/`, then
restart. `/config/smartcat.db` stays; delete it to drop the history.

Unverified until it runs against the live Whisker account: the Basement
(LR5) `PET_VISIT` field names, which are undocumented, so the integration
parses them tolerantly and keeps raw records; and the LR4 activity query's
`endTimestamp` paging. Check the first refresh's log and the backfill progress.
