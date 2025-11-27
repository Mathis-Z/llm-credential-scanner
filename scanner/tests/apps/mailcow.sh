#!/bin/bash

git clone https://github.com/mailcow/mailcow-dockerized.git --depth 1
cd mailcow-dockerized

# set hostname and accept default timezone and code branch
echo "127.0.0.1\n\n\n" | ./generate_config.sh

docker network prune -f
docker compose up
