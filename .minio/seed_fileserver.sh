#!/bin/bash
set -e

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

# Function to recursively get all files in a directory
get_all_files() {
    local dir="$1"
    local base="$2"
    for entry in "$dir"/*; do
        [ -e "$entry" ] || continue
        if [ -d "$entry" ]; then
            get_all_files "$entry" "$base"
        elif [ -f "$entry" ]; then
            rel_path="${entry#$base/}"
            echo "$rel_path"
        fi
    done
}

# For each folder in the data directory, create a bucket and upload its files
for dir in "$DATA_DIR"/*; do
    [ -d "$dir" ] || continue
    bucket=$(basename "$dir")
    echo "Creating bucket: $bucket"
    mc mb "$ALIAS/$bucket" || true

    echo "Uploading files from $dir to bucket: $bucket"
    while IFS= read -r rel_path; do
        file="$dir/$rel_path"
        echo "Uploading $file as $rel_path"
        mc cp "$file" "$ALIAS/$bucket/$rel_path"
    done < <(get_all_files "$dir" "$dir")
done

# Generate configuration file mapping bucket/file to a presigned URL with no expiry
echo "{" > "$CONFIG_FILE"
firstEntry=true
for dir in "$DATA_DIR"/*; do
    [ -d "$dir" ] || continue
    bucket=$(basename "$dir")
    while IFS= read -r rel_path; do
        file="$dir/$rel_path"
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
    done < <(get_all_files "$dir" "$dir")
done
echo "}" >> "$CONFIG_FILE"
echo "Configuration file generated at: $CONFIG_FILE"
