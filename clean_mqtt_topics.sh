#!/bin/sh
set -eu

if [ "${1:-}" != "--apply" ] || [ "$#" -ne 1 ]; then
  echo "Usage: MQTT_CLIENT_CONFIG=/private/mosquitto-client.conf $0 --apply" >&2
  exit 2
fi

if [ -z "${MQTT_CLIENT_CONFIG:-}" ] || [ ! -r "$MQTT_CLIENT_CONFIG" ]; then
  echo "Set MQTT_CLIENT_CONFIG to a readable, private Mosquitto client config file." >&2
  exit 2
fi

# Mosquitto reads the broker address and credentials from the local config file.
# Only retained messages are cleared; live messages are left alone.
mosquitto_sub -o "$MQTT_CLIENT_CONFIG" -t '#' --remove-retained --retained-only --quiet
