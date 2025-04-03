#!/bin/bash
set -e

# Seeds MinIO buckets and files from ./data

# Alias for the MinIO server
ALIAS="local"
MINIO_URL="http://localhost:9000"
# Use credentials from the env vars (with fallback values)
ACCESS_KEY="localuser"
SECRET_KEY="localpass"

# Configure alias if not already set
mc alias set "$ALIAS" "$MINIO_URL" "$ACCESS_KEY" "$SECRET_KEY"

DATA_DIR="./.minio/data"

if [ ! -d "$DATA_DIR" ]; then
    echo "Directory '$DATA_DIR' does not exist."
    exit 1
fi

# For each folder in the data directory, create a bucket and upload its files, overwriting existing objects
OVERWRITE_FLAG="--overwrite"
for dir in "$DATA_DIR"/*/; do
    bucket=$(basename "$dir")
    echo "Creating bucket: $bucket"
    mc mb "$ALIAS/$bucket" || true

    echo "Uploading files from $dir to bucket: $bucket"
    for file in "$dir"*; do
        if [ -f "$file" ]; then
            mc cp "$file" "$ALIAS/$bucket"
        fi
    done
done
