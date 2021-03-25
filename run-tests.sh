#!/usr/bin/env bash

set -a
cat > .env.test << EOT
POSTGRES_HOST=0.0.0.0
POSTGRES_PORT=5434
POSTGRES_DB=test
POSTGRES_USER=user
POSTGRES_PASSWORD=password
EOT
docker run -d --rm --name test-db -p 5434:5432 --env-file .env.test postgres:12-alpine
docker exec test-db bash -c 'until pg_isready; do sleep 1; done'
sleep 3
source .env.test
pytest
status=$?
docker stop test-db
set +a
[ $status -eq 0 ] || exit 1
