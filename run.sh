#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
IMAGE_NAME="${OM_APPLY_IMAGE:-openmetadata-apply}"
RESOURCE_PATH="${OPENMETADATA_RESOURCE_FILE:-$SCRIPT_DIR/resources}"

if [ -d "$RESOURCE_PATH" ]; then
  CONTAINER_RESOURCE_PATH="/data/resources"
else
  CONTAINER_RESOURCE_PATH="/data/resources.yml"
fi

docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
docker run --rm \
  --env-file "$SCRIPT_DIR/.env" \
  -v "$RESOURCE_PATH:$CONTAINER_RESOURCE_PATH:ro" \
  "$IMAGE_NAME" \
  --file "$CONTAINER_RESOURCE_PATH" "$@"
