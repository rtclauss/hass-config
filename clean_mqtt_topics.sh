#!/bin/sh
echo "cleaning " $1 " :: usage: cleanmqtt <host> <user> <password>"
mosquitto_sub -h REDACTED -u mqtt -P REDACTED -t "#" -v | while read line _; do mosquitto_pub -h REDACTED -u mqtt -P REDACTED -t "'$line'" -r -n; done
