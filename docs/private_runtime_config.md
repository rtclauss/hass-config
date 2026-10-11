# Private runtime configuration

The public repository contains only a Zigbee2MQTT example. Keep the active
`zigbee2mqtt/configuration.yaml`, its `secret.yaml`, and generated backup files
on the Home Assistant host. Do not copy the example over a running installation:
changing the Zigbee network key requires re-pairing devices.

## Existing checkout migration

Removing a tracked file in Git also deletes it from an existing checkout during
`git pull`. Before updating a Home Assistant checkout that still tracks these
files, preserve its live copies in the ignored `.private-runtime-backup/`
directory **on that host**. Preserve `travis_secrets.yaml` too if present:

```sh
mkdir -p .private-runtime-backup/zigbee2mqtt
cp -p zigbee2mqtt/configuration.yaml zigbee2mqtt/secret.yaml \
  zigbee2mqtt/configuration_backup*.yaml \
  .private-runtime-backup/zigbee2mqtt/
test ! -f travis_secrets.yaml || \
  cp -p travis_secrets.yaml .private-runtime-backup/
```

Check that every copied file matches its source before updating. After the
checkout update, restore the private files from that directory **before
restarting Home Assistant or Zigbee2MQTT**:

```sh
cp -p .private-runtime-backup/zigbee2mqtt/*.yaml zigbee2mqtt/
test ! -f .private-runtime-backup/travis_secrets.yaml || \
  cp -p .private-runtime-backup/travis_secrets.yaml .
git check-ignore zigbee2mqtt/configuration.yaml zigbee2mqtt/secret.yaml \
  .private-runtime-backup/zigbee2mqtt/configuration.yaml
```

The current live Home Assistant checkout has already had these seven files
copied and byte-verified in its `.private-runtime-backup/` directory. Keep that
directory private until deployment and verification finish.

Home Assistant and ESPHome secrets also remain in their ignored `secrets.yaml`
files. CI uses `travis_secrets.example.yaml`, which contains synthetic values.
Do not use those values on a live system.

The root `automations.yaml` is Home Assistant UI-owned on the live host. The
public `automations.example.yaml` is an empty fixture for CI, not a deployment
file. The live file has already been byte-verified under
`.private-runtime-backup/current-config/automations.yaml` on the host. Before
updating its Git checkout, stop any automatic pull and automation reload, then
run this from `/config` after confirming that private backup still matches the
live file:

```sh
cmp automations.yaml .private-runtime-backup/current-config/automations.yaml
git restore -- automations.yaml  # release the tracked, locally edited path
# Update the checkout using the Zigbee steps above and docs/custom_components.md.
cp -p .private-runtime-backup/current-config/automations.yaml automations.yaml
git check-ignore automations.yaml
```

Restore the private copy immediately after the checkout update, before
restarting or reloading automations. Never copy the public example over the
live file.

## UI-owned dashboards

Home Assistant owns its Lovelace files in `.storage/`; the public repository
does not track them. The four formerly tracked files have byte-identical live
copies, already preserved in the ignored
`.private-runtime-backup/current-config/.storage/` directory on the host.
Before updating that checkout, verify each copy with `cmp`. The checkout
update removes the formerly tracked files; restore the private copies from
the backup immediately afterward, before restarting Home Assistant. Leave
all other `.storage` files in place. Change dashboard content through Home
Assistant's dashboard API or UI, not by editing `.storage` directly.

```sh
for backup in .private-runtime-backup/current-config/.storage/*; do
  cmp ".storage/${backup##*/}" "$backup"
done
# Update the checkout using the coordinated HACS/Zigbee migration.
cp -p .private-runtime-backup/current-config/.storage/* .storage/
git check-ignore .storage/lovelace_dashboards
```

Afterward, confirm the same dashboards load through Home Assistant's dashboard
API or UI. The file copy is only for the one-time Git migration; use the API or
UI for subsequent dashboard changes.

CI tests use two small synthetic fixtures in `tests/fixtures/`. Set
`HA_DASHBOARD_PATH` and `HA_STRATEGY_DASHBOARD_PATH` to the corresponding
private dashboard exports when running the same checks against live content;
do not commit those exports.

After changing the live Zigbee2MQTT roster, pass its private configuration to
`scripts/check_z2m_availability_roster.py -` on stdin. The checker compares it
with `packages/z2m_availability.yaml` and prints counts only.

The active availability package contains private Zigbee friendly names and
entity IDs. It is ignored by Git; `examples/z2m_availability.yaml` is a small
synthetic package used only by tests and CI. Before updating an older checkout,
copy the active package to
`.private-runtime-backup/current-config/packages/z2m_availability.yaml` and
byte-compare it with the original. Restore it immediately after the update,
before restarting or reloading Home Assistant. CI copies the example into
`packages/` only in its disposable checkout; never use the example on the live
host. Re-run the roster checker against the restored package and private
Zigbee2MQTT configuration after migration.

## Private zones

The zone package reads private names and coordinates from `secrets.yaml`.
The live `secrets.yaml` already has these keys, and its pre-change contents
were byte-verified under
`.private-runtime-backup/current-config/secrets.before-zone-privacy.yaml`.
Keep that file private. Before updating another installation, populate the
`private_zone_XX_*` keys with its own zone values. The values in
`travis_secrets.example.yaml` are synthetic and intended only for CI.

## Archived AppDaemon and ESPHome comments

The old `appdaemon.bak/` tree is ignored. Its 30 live files have been copied
and byte-verified under `.private-runtime-backup/appdaemon.bak/` before Git
removes the three formerly tracked files. Restore the tree from that private
backup after the checkout update if it is still needed locally. The inactive
Bluetooth plant sensor examples in `esphome/office-bt-proxy.yaml` were removed
because their comments contained device addresses; active ESPHome configuration
was not changed.
Three old bed-occupancy Python copies were also untracked and ignored; their
live copies are byte-verified under `.private-runtime-backup/appdaemon-legacy/`.
The active `appdaemon/apps/bed_occupancy.py` remains tracked.
