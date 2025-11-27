#!/bin/bash

curl -L https://raw.githubusercontent.com/RARgames/4gaBoards/main/docker-compose.yml -o docker-compose.yml
docker rm -f $(docker ps -aq) && docker network prune -f
docker compose up
