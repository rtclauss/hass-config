#!/bin/bash
docker-compose pull && docker-compose up --no-start &&  docker-compose restart
