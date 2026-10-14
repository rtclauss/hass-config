# Private runtime configuration

## Rendered private YAML

For values embedded in Jinja, YAML keys, or other positions that cannot use
`!secret`, public templates may contain `@@PRIVATE:key@@` markers. Use
`@@PRIVATE:key|json@@` when the marker is an entire YAML string scalar. The
`docs/private_config_manifest.json` file lists each template and its ignored
runtime YAML output. Keep real string values in the ignored
`.private-runtime-config/values.json` file. Run
`python3 scripts/render_private_config.py` before reloading Home Assistant;
`--check` reports stale outputs without writing. The renderer validates every
required key before writing, requires every output to be untracked and
Git-ignored, creates files with owner-only permissions, and does not print
values. CI validates the committed manifest and
`examples/private_values.example.json` without writing outputs; that example
must contain only synthetic values. The media package is the first manifest
target.

## Private media package

`packages/media_player.yaml` is generated locally from
`private_templates/media_player.yaml.tmpl` and the ignored
`.private-runtime-config/values.json`. The private mapping holds playlist and
provider item IDs, stream choices, playlist annotations and labels, and an NFC
tag ID. The committed example values render a synthetic package for CI. Never
render those example values on the live host.

The current live media package matched the former tracked file byte for byte.
A fresh copy was byte-verified at
`.private-runtime-backup/current-config/packages/media_player.before-template-2026-10-14.yaml`
on that host. Preserve that backup and the private mapping before updating its
checkout. The live mapping is staged with 334 keys under a root-owned
directory (mode 0700); its file is mode 0600. After Git stops tracking the
package, run the renderer as an account that can read that mapping (root on
the current host), then run `python3 scripts/render_private_config.py --check`
before any Home Assistant reload. The private render is byte-identical to the
live baseline; the example render is only for CI.

The retained-topic cleanup utility reads broker connection settings from a
private Mosquitto client config file, never from committed shell arguments.
For Mosquitto clients 2.1 or newer, put `-h`, `-u`, and `-P` options on separate
lines in a root-readable file outside the repository or under the ignored
`.private-runtime-config/` directory. Set `MQTT_CLIENT_CONFIG` to that file and
run `clean_mqtt_topics.sh --apply` only when clearing all retained topics is
intended. The script does not run during deployment.

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

## Private feed and domain alert

The Birdweather REST sensors, domain-expiry notifications, and water-meter REST
commands also read private scalar values from root `secrets.yaml`. The live
values were copied from the active packages into private keys after the
previous secret file was
byte-verified at
`.private-runtime-backup/current-config/secrets.before-feed-domain-privacy.yaml`.
The second addition was backed up at
`.private-runtime-backup/current-config/secrets.before-watermeter-privacy.yaml`.
CI uses synthetic station and water-meter URLs and an example domain.

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

## Private network endpoints

The Zigbee/Z-Wave, aircraft, car, and vacuum-map packages read local URLs and MQTT
reconfiguration payloads from `secrets.yaml`. The live secret file has the
matching `private_*` keys. Its previous contents were byte-verified under
`.private-runtime-backup/current-config/secrets.before-network-privacy.yaml`.
The live packages remain unchanged until deployment. CI uses synthetic
endpoints and payloads in `travis_secrets.example.yaml`.

## Private device identifiers

The light, workday, and TV packages resolve their Zigbee IEEE identifiers
through `!secret`. The live values were added to the ignored `secrets.yaml`
after preserving its prior contents at
`.private-runtime-backup/current-config/secrets.before-device-ids.yaml`.
The live package files remain unchanged until deployment. CI uses synthetic
IEEE values, and the Parasoll selector displays a synthetic example.

## Private AppDaemon watchdog settings

The AppDaemon reboot watchdog reads its two TCP probe targets and notification
service from `!secret` values in `appdaemon/apps/apps.yaml`; a living-room
remote IEEE is private too. The live root `secrets.yaml` contains the matching
values and was byte-verified before this addition at
`.private-runtime-backup/current-config/secrets.before-appdaemon-privacy.yaml`.
The live AppDaemon files remain unchanged until deployment. If the watchdog
lacks probes or an alert destination, it disables scheduling instead of
rebooting without a usable check or notification. CI uses synthetic values.

The RTL-SDR watchdog's primary and secondary notification destinations are
also `!secret` values. The live values were copied from its active `apps.yaml`
after preserving root secrets at
`.private-runtime-backup/current-config/secrets.before-rtlsdr-notify-privacy.yaml`.
Missing the primary destination disables scheduling, including dry-run checks.
