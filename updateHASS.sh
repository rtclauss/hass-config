#!/bin/bash
docker build -t example_owner/home-assistant:latest . 
docker-compose pull && docker-compose restart
