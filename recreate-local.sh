#!/bin/bash

# Convenience script to recreate the local environment.

docker compose -f docker-compose.signoz.yml down -v

docker compose --profile search --profile app down -v

COMPOSE_EXPERIMENTAL_GIT_REMOTE=1 docker compose -f docker-compose.signoz.yml up -d

docker compose --profile search --profile app up -d

poetry run alembic upgrade head

./.minio/seed_fileserver.sh
