#!/bin/bash

# Convenience script to recreate the local environment.

docker compose --profile instrumentation --profile search --profile app down -v

docker compose --profile instrumentation --profile search --profile app up -d

poetry run alembic upgrade head

./.minio/seed_fileserver.sh
