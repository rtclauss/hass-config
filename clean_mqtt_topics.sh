#!/bin/sh
echo "cleaning " $1 " :: usage: cleanmqtt <host> <user> <password>"
mosquitto_sub -h 10.24.1.11 -u mqtt -P XQydytH7WDez -t "#" -v | while read line _; do mosquitto_pub -h 10.24.1.11 -u mqtt -P XQydytH7WDez -t "'$line'" -r -n; done
