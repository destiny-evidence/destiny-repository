#!/bin/bash
set -e
shopt -s globstar

# Seeds MinIO buckets and files from ./data

# Alias for the MinIO server
ALIAS="${ALIAS:-local}"
MINIO_URL="${MINIO_URL:-http://localhost:9000}"
ACCESS_KEY="${MINIO_ACCESS_KEY:-localuser}"
SECRET_KEY="${MINIO_SECRET_KEY:-localpass}"

# Configure alias if not already set
mc alias set "$ALIAS" "$MINIO_URL" "$ACCESS_KEY" "$SECRET_KEY"

DATA_DIR="${MINIO_SEED_DATA_DIR:-./.minio/data}"
CONFIG_FILE="${MINIO_PRESIGNED_URL_FILEPATH:-./.minio/presigned_urls.json}"

if [ ! -d "$DATA_DIR" ]; then
    echo "Directory '$DATA_DIR' does not exist."
    exit 1
fi

# For each folder in the data directory, create a bucket and upload its files recursively, preserving subfolder paths
for dir in "$DATA_DIR"/*/; do
    bucket=$(basename "$dir")
    echo "Creating bucket: $bucket"
    mc mb "$ALIAS/$bucket" || true

    echo "Uploading files from $dir to bucket: $bucket"
    for file in "$dir"**/*; do
        if [ -f "$file" ]; then
            rel_path="${file#$dir}"
            echo "Uploading $file as $rel_path"
            mc cp "$file" "$ALIAS/$bucket/$rel_path"
        fi
    done
done

# Generate configuration file mapping bucket/file to a presigned URL with no expiry
echo "{" > "$CONFIG_FILE"
firstEntry=true
for dir in "$DATA_DIR"/*/; do
    bucket=$(basename "$dir")
    for file in "$dir"**/*; do
        if [ -f "$file" ]; then
            rel_path="${file#$dir}"
            raw=$(mc share download --expire 168h "$ALIAS/$bucket/$rel_path")
            url=""
            while IFS= read -r line; do
                case "$line" in
                    Share:*) url="${line#Share: }"; break ;;
                esac
            done <<< "$raw"
            if [ "$firstEntry" = true ]; then
                firstEntry=false
            else
                echo "," >> "$CONFIG_FILE"
            fi
            echo "  \"${bucket}/${rel_path}\": \"${url}\"" >> "$CONFIG_FILE"
        fi
    done
done
echo "}" >> "$CONFIG_FILE"
echo "Configuration file generated at: $CONFIG_FILE"
