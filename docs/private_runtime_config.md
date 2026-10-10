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
updating its Git checkout, preserve the live copy outside the tracked path;
after updating, restore that copy before restarting or reloading automations.
Never copy the public example over the live file.

After changing the live Zigbee2MQTT roster, pass its private configuration to
`scripts/check_z2m_availability_roster.py -` on stdin. The checker compares it
with `packages/z2m_availability.yaml` and prints counts only.
