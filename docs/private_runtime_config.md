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
provider item IDs, stream choices, playlist annotations and labels, and NFC
device and tag IDs. The committed example values render a synthetic package
for CI and a fresh local test checkout. Never
render those example values on the live host.

The current live media package matched the former tracked file byte for byte.
A fresh copy was byte-verified at
`.private-runtime-backup/current-config/packages/media_player.before-template-2026-10-14.yaml`
on that host. Preserve that backup and the private mapping before updating its
checkout. The live mapping is staged under a root-owned
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

The file-backed guest dashboard is also private. Render `ui-guest.yaml` from
`private_templates/ui-guest.yaml.tmpl` so its title and location-specific
weather entity and station sensor come from the ignored mapping. Preserve the live YAML before
updating an older checkout; Git removes its formerly tracked copy. Render all
manifest targets before reloading the guest dashboard. The public README links
to the template rather than the private rendered output.

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

The zone package is rendered from `private_templates/zone.yaml.tmpl` and the
ignored private mapping. The template hides person and place names, zone keys,
presence identifiers, and secret-key names that identify private locations.
Its scalar names and coordinates still resolve through root `secrets.yaml`.
The live `secrets.yaml` already has those values, and its pre-change contents
were byte-verified under
`.private-runtime-backup/current-config/secrets.before-zone-privacy.yaml`.
Keep that file private. Before updating another installation, populate the
`private_zone_XX_*` keys and the private render mapping with its own values.
The current live zone file is byte-verified at
`.private-runtime-backup/current-config/packages/zone.before-template-2026-10-14.yaml`.
The real zone render matches the tracked source byte for byte; with live
secrets resolved, it is structurally equivalent to the live file. Render it
from the private mapping after Git stops tracking it and before any reload.
The values in `travis_secrets.example.yaml` and
`examples/private_values.example.json` are synthetic and intended only for
tests and CI.

## Shared presence identity

The zone package produces the canonical presence entities, and 17 other
Home Assistant packages consume them. All 18 packages now render the same
private person identifier from the ignored mapping; synthetic CI values use
one matching example identifier. The template migration does not rename any
live entity: all real renders are byte-identical to their tracked baselines.
The 17 additional live package files were byte-verified under
`.private-runtime-backup/current-config/presence-template-2026-10-14/packages/`.
Four package files in the full zone/presence set differ from their tracked
source because earlier scalar values moved to `!secret`; resolving the live
secrets confirms structural equivalence. Update the live checkout and render
every manifest target as one deployment before reloading automations or
packages. Do not deploy the synthetic render to the live host.

## Private flight and airport data

`packages/flight_status.yaml` is rendered from a public template with its
airport lookup entries, home airport aliases, fallback coordinates, and
personal calendar entity in the ignored mapping. The existing trips template
uses the same airport alias keys. The real renders of both packages match
their tracked baselines byte for byte. The live flight package matches its
tracked baseline and is backed up at
`.private-runtime-backup/current-config/packages/flight_status.before-template-2026-10-16.yaml`.
Synthetic examples use invented airport codes and places for CI. Render all
manifest targets together before reloading either package on the live host.

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

The Home Assistant instance name, unit system, currency, country, timezone,
and formerly literal trusted network now also resolve from the ignored root
`secrets.yaml`. The live values were preserved without behavior changes after
its prior contents were byte-verified at
`.private-runtime-backup/current-config/secrets.before-core-privacy-2026-10-18.yaml`.
CI uses synthetic profile values and a documentation network.

## Private device identifiers

The light, workday, and TV packages resolve their Zigbee IEEE identifiers
through `!secret`. The live values were added to the ignored `secrets.yaml`
after preserving its prior contents at
`.private-runtime-backup/current-config/secrets.before-device-ids.yaml`.
The live package files remain unchanged until deployment. CI uses synthetic
IEEE values, and the Parasoll selector displays a synthetic example.

## Private AppDaemon watchdog settings

The AppDaemon reboot watchdog reads its two TCP probe targets and notification
service from the ignored, rendered `appdaemon/apps/apps.yaml`; a living-room
remote IEEE is private too. The live root `secrets.yaml` contains the matching
values used by the former tracked configuration and was byte-verified at
`.private-runtime-backup/current-config/secrets.before-appdaemon-privacy.yaml`.
The live AppDaemon files remain unchanged until deployment. If the watchdog
lacks probes or an alert destination, it disables scheduling instead of
rebooting without a usable check or notification. CI uses synthetic values.

The RTL-SDR watchdog's primary and secondary notification destinations are
also rendered privately. The live values were copied from its active `apps.yaml`
after preserving root secrets at
`.private-runtime-backup/current-config/secrets.before-rtlsdr-notify-privacy.yaml`.
Missing the primary destination disables scheduling, including dry-run checks.

The active AppDaemon `apps.yaml` and vacuum-stall YAML are rendered from public
templates and the ignored mapping. The render retains the active add-on's
notification destinations, tracker entities, city-specific weather sensors,
network probes, and device identifier. Its only intended additions are explicit
tracker friendly-name and iOS speed-source arguments, which replace private
defaults in Python. The active add-on files and inactive bed-history/Schedy
files were byte-verified under
`.private-runtime-backup/appdaemon-active-2026-10-16/` on the host. Render and
check all manifest targets before synchronizing AppDaemon. Never stage or push
the generated YAML or the inactive history files.

## Personal mobile notification targets

Two other mobile notification targets use `mobile_notify_service_01` and
`mobile_notify_service_02` in the ignored values mapping. The latter also has
root `!secret` consumers. Their live mapping and root secret entries were
backed up and updated together; changing either mobile app registration requires
updating both consumers for that target.

## Private vehicle and local market identifiers

`vehicle_entity_slug`, `vehicle_display_name`, `home_city_slug`,
`home_city_title`, and `home_postal_code` belong in the ignored values mapping.
The matching public example uses synthetic values. The renderer validates every
required key and writes ignored outputs atomically. The live mapping was backed
up before these keys were added.
