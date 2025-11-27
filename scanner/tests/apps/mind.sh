#!/bin/bash

docker run \
    --name mind \
    -v "mind-db:/app/db" \
    -e TZ=Europe/Amsterdam \
    -p 8080:8080 \
    mrcas/mind:latest
