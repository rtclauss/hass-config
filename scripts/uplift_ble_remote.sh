#!/bin/sh

set -eu

CONFIG_FILE="${UPLIFT_BLE_REMOTE_CONFIG:-/config/scripts/uplift_ble_remote.conf}"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Missing config file: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
. "$CONFIG_FILE"

if [ -z "${SSH_TARGET:-}" ]; then
  echo "SSH_TARGET must be set in $CONFIG_FILE" >&2
  exit 1
fi

REMOTE_COMMAND="${REMOTE_COMMAND:-/usr/local/bin/uplift-desk-remote}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-}"
SSH_KNOWN_HOSTS="${SSH_KNOWN_HOSTS:-}"
SSH_STRICT_HOST_KEY_CHECKING="${SSH_STRICT_HOST_KEY_CHECKING:-yes}"
ACTION="${1:-}"

if [ -z "$ACTION" ]; then
  echo "Usage: $0 <action>" >&2
  exit 1
fi

set -- ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking="$SSH_STRICT_HOST_KEY_CHECKING" \
  -p "$SSH_PORT"

if [ -n "$SSH_KEY" ]; then
  set -- "$@" -i "$SSH_KEY"
fi

if [ -n "$SSH_KNOWN_HOSTS" ]; then
  set -- "$@" -o UserKnownHostsFile="$SSH_KNOWN_HOSTS"
fi

exec "$@" \
  "$SSH_TARGET" \
  "$REMOTE_COMMAND" \
  "$ACTION"
