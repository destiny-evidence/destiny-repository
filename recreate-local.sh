#!/bin/bash

# Convenience script to recreate the local environment.

docker compose --profile search --profile app --profile ui down -v

docker compose --profile search --profile app --profile ui up -d

echo "Applying database migrations..."
uv run alembic upgrade head

# Seed the database with some local data
echo "Seeding local database..."
PGPASSWORD=localpass psql -U localuser -h 0.0.0.0 -p 5432 -d destiny_dev -f ".db_seed/local.sql"

# Index the local data into elasticsearch
echo "Indexing local data into Elasticsearch..."
sleep 1  # If I take this sleep out the script fails consistently don't ask me why I hate bash (Jack)
curl -X POST "http://127.0.0.1:8000/v1/system/indices/reference/repair/?rebuild=true"
