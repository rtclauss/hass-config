#!/bin/bash
docker build -t rtclauss/home-assistant:latest . 
docker-compose pull && docker-compose restart
