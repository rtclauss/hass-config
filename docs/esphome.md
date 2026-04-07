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

- `esphome/bedloadcell1.yaml`
- `esphome/bedloadcell2.yaml`
- `esphome/tikiroom.yaml`
- `esphome/watersoftener.yaml`

Those configs target ESP8266 hardware, which does not provide the ESP32 Bluetooth proxy stack used by Bermuda.

## Runtime note

Bermuda rooming depends on Home Assistant runtime setup in addition to the repo config. The ESPHome device must be added as a Bluetooth proxy in Home Assistant and assigned to the correct area so Bermuda can turn advertisements from devices like the iPhone and Apple Watch into room hints.
