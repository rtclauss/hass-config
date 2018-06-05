#!/bin/sh
echo "cleaning " $1 " :: usage: cleanmqtt <host> <user> <password>"
mosquitto_sub -h $1 -u $2 -P $3 -t "#" -v | while read line _; do mosquitto_pub -h $1 -u $2 -P $3 -t "$line" -r -n; done
