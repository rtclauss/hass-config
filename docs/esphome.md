# ESPHome Layout

## Shared packages

ESPHome Bluetooth proxies now share two common packages under `esphome/packages/common/`:

- `base.yaml` centralizes Wi-Fi, native API, OTA, Home Assistant time sync, captive portal, and diagnostic entities for status, uptime, Wi-Fi signal, IP/MAC, and ESPHome version.
- `bluetooth_proxy.yaml` centralizes the ESP32 `esp-idf` target, Bluetooth proxy stack, BLE tracker, and `xiaomi_ble` support.

That keeps room-specific files focused on local behavior only. Today the office proxy is the only node with extra Apple Watch RSSI logic, so that logic stays in `esphome/office-bt-proxy.yaml` while the generic Bluetooth proxy wiring lives in the shared package.

## Bermuda BLE coverage

The current ESPHome nodes that can contribute BLE advertisements to Home Assistant and Bermuda are:

- `esphome/bluetoothproxy1.yaml` (`denbluetoothproxy`)
- `esphome/office-bt-proxy.yaml` (`office-bt-proxy`)
- `esphome/livingroombtproxy.yaml` (`diningroom-bt-proxy`)

There is no bedroom BLE-capable ESPHome node in this repository today.

The current ESPHome nodes that cannot participate in Bermuda BLE scanning are:

- `esphome/tikiroom.yaml`
- `esphome/watersoftener.yaml`

Those configs target ESP8266 hardware, which does not provide the ESP32 Bluetooth proxy stack used by Bermuda.

## Runtime note

Bermuda rooming depends on Home Assistant runtime setup in addition to the repo config. The ESPHome device must be added as a Bluetooth proxy in Home Assistant and assigned to the correct area so Bermuda can turn advertisements from devices like the iPhone and Apple Watch into room hints.

## Private credentials

Bluetooth proxy OTA passwords, fallback access point passwords, the project
name, and the resident display name are read from the ignored
`esphome/secrets.yaml` on the live host. CI copies the synthetic
`examples/esphome_secrets.example.yaml` instead. Never use those example
values on a live device. The former literal values are present in old Git
history until the planned history rewrite, so moving them into secrets does
not complete credential rotation.

The live ESPHome YAML files and secrets file were copied and byte-verified
under `.private-runtime-backup/esphome-credentials-2026-10-18/` before this
change. The initial secrets migration preserves the currently installed OTA
passwords so the next update remains possible. Rotate each OTA password with
ESPHome's documented [staged password procedure](https://esphome.io/components/ota/esphome/#changing-an-existing-password):
upload a temporary private configuration that authenticates with the old
password and sets the new password at boot, confirm the device comes back,
then update the private secret and deploy the final public configuration.
Keep temporary rotation YAML out of Git. Change fallback access point
passwords in the secrets file before each firmware update, then verify the
node reconnects through its normal Wi-Fi and API path.
