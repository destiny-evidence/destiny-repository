#!/bin/bash

# Convenience script to recreate the local environment.

docker compose down -v

docker compose --profile search up -d

poetry run alembic upgrade head

./.minio/seed_fileserver.sh
