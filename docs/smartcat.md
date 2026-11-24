# Smart Cat (cat insights for the Litter-Robots)

Smart Cat is a custom integration (`smartcat`) that recreates the useful parts
of Whisker+ locally: per-cat visits, visit duration, a time-of-visit pattern,
multi-year history, outlier and trend detection, and forecasts for when each
Litter-Robot's waste drawer fills and its litter needs topping up. This repo
holds only the Home Assistant side: the notifications package
(`packages/smartcat.yaml`), the Cats dashboard (`lovelace/dashboards/cats.yaml`),
and their tests. The integration code lives in its own repository and is
installed through HACS like every other custom integration; git does not track
it (see [custom_components.md](custom_components.md)).

Smart Cat is not a diagnostic tool and does not replace veterinary care.

## Install

1. Install Smart Cat from HACS (custom repository), then restart.
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
| `sensor.splashy_visits_today` | Visits today; `daily_counts` (14 d), `hourly_histogram_30d`, `baseline_mean` |
| `sensor.splashy_last_visit`, `_last_visit_duration`, `_average_visit_duration` | Visit timing |
| `sensor.splashy_weight`, `_weight_trend` | 7-day median of trusted weigh-ins; Theil-Sen lb/week |
| `sensor.<robot>_waste_drawer_full_forecast`, `_litter_refill_forecast` | Timestamps; attributes hold rate per cycle, cycles/day, days remaining, method |
| `sensor.<robot>_cycles_per_day`, `sensor.<robot>_visits_today` | Robot activity (on the existing Litter-Robot devices) |
| `binary_sensor.smart_cat_new_cat_suspected` | Weigh-ins that match no known cat |

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
- Forecasts are dashboard-only. The `litter_robot` package still owns the
  replace-bag and add-litter tasks.

## Adding a cat

After `smartcat.add_cat`, add `binary_sensor.<cat>_needs_attention` to the
trigger list of `smartcat_cat_needs_attention`, copy the Splashy section of
the Cats dashboard, and extend `tests/test_smartcat_package.py`.

## Validation and rollback

Run `uv run --with pytest pytest`. `tests/test_smartcat_package.py` covers the
push decision matrix (new, added, replaced, drifted, reordered, partially
resolved, recovered), startup/reload suppression, tag-based clearing, link
rendering, and dashboard registration.

Rollback: remove `packages/smartcat.yaml`, the `db-cats` dashboard entry and
`lovelace/dashboards/cats.yaml`, then reload. Removing the integration
leaves `/config/smartcat.db`; delete it to drop the history.

Unverified until it runs against the live Whisker account: the Basement
(LR5) `PET_VISIT` field names, which are undocumented, so the integration
parses them tolerantly and keeps raw records; and the LR4 activity query's
`endTimestamp` paging. Check the first refresh's log and the backfill progress.
