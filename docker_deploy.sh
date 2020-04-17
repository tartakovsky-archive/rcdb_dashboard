#!/bin/bash

version=$(cat .version)
image_name="rcdb/execution-$version"

./docker_build.sh $image_name

if [ -z "$SENTRY_DSN" ]; then
  echo "SENTRY_DSN is missing, can't build docker image"
  exit 1
fi

if [ -z "$KAIKO_API_KEY" ]; then
  echo "KAIKO_API_KEY is missing, can't build docker image"
  exit 1
fi

docker-compose -f .packaging/docker-compose.yaml up

