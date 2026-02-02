#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="dicom-mcp"
IMAGE_TAG="latest"
OUTPUT_FILE="dicom-mcp.tar.gz"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Building ${IMAGE_NAME}:${IMAGE_TAG} ..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" "$PROJECT_ROOT"

echo "Saving image to ${OUTPUT_FILE} ..."
docker save "${IMAGE_NAME}:${IMAGE_TAG}" | gzip > "${SCRIPT_DIR}/${OUTPUT_FILE}"

echo ""
echo "Done. Image saved to deploy/${OUTPUT_FILE}"
echo "Copy it to your server and run install.sh"
