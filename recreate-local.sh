#!/bin/bash

# Convenience script to recreate the local environment.

docker compose --profile search --profile app down -v

docker compose --profile search --profile app up -d

uv run alembic upgrade head

./.minio/seed_fileserver.sh

PGPASSWORD=localpass psql -U localuser -h 0.0.0.0 -p 5432 -d destiny_dev -f ".db_seed/local.sql"
