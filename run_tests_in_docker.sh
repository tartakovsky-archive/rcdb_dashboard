#!/bin/bash
./docker_build.sh && DOCKER_IMAGE_NAME=rcdb/execution:$(cat .version) docker-compose -f .packaging/docker-compose.yaml run -e LOG_LEVEL=DEBUG web pytest
