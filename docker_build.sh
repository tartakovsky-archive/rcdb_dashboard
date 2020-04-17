#!/bin/bash

if [ -z "$GITHUB_TOKEN" ]; then
  echo "GITHUB_TOKEN is missing, can't build docker image"
  exit 1
fi

image_name=${1:-"rcdb/execution-$(cat .version)"}
echo "Building docker image: $image_name"
docker build -t $image_name -f .packaging/Dockerfile .