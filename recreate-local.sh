#!/bin/bash

# Convenience script to recreate the local environment.

docker compose down -v

docker compose up -d

for i in {5..1}; do
    echo -ne "Waiting for boot, continuing in $i seconds...\r"
    sleep 1
done
echo ""

poetry run alembic upgrade head

./.minio/seed_fileserver.sh
