# Private runtime configuration

The public repository contains only a Zigbee2MQTT example. Keep the active
`zigbee2mqtt/configuration.yaml`, its `secret.yaml`, and generated backup files
on the Home Assistant host. Do not copy the example over a running installation:
changing the Zigbee network key requires re-pairing devices.

Home Assistant and ESPHome secrets also remain in their ignored `secrets.yaml`
files. CI uses `travis_secrets.example.yaml`, which contains synthetic values.
Do not use those values on a live system.

After changing the live Zigbee2MQTT roster, pass its private configuration to
`scripts/check_z2m_availability_roster.py -` on stdin. The checker compares it
with `packages/z2m_availability.yaml` and prints counts only.
