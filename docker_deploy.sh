#!/bin/bash

command=$1

if [ -z "$GITHUB_TOKEN" ]; then
  echo "GITHUB_TOKEN is missing, can't build docker image"
  exit 1
fi

version=$(cat .version)
image_name="rcdb/execution:$version"

./docker_build.sh $image_name

image_exists=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep "$image_name")

if [ -z "$image_exists" ]; then
  echo "Docker image `$image_name` doesn't exists, check docker_build.sh works properly"
  exit 1
fi

if [ -z "$SENTRY_DSN" ]; then
  echo "SENTRY_DSN is missing, can't build docker image"
  exit 1
fi

if [ -z "$KAIKO_API_KEY" ]; then
  echo "KAIKO_API_KEY is missing, can't build docker image"
  exit 1
fi


export DOCKER_IMAGE_NAME=$image_name
export DOCKER_STACK_NAME=rcdb_exec
#export POSTGRES_HOST="$DOCKER_STACK_NAME"_db

if [[ $command = "logs" ]]; then
  docker-compose -f .packaging/docker-compose.yaml logs -f
fi

if [[ $command = "up" ]]; then
  docker-compose -f .packaging/docker-compose.yaml up -d
fi

if [[ $command = "stop" ]]; then
  docker-compose -f .packaging/docker-compose.yaml stop
fi


# > dc.yaml
# cat dc.yaml
# cat dc.yaml | docker stack deploy --compose-file - rcdb_exec
