#!/usr/bin/env bash
set -euo pipefail

IMAGE_FILE="dicom-mcp.tar.gz"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "${SCRIPT_DIR}/${IMAGE_FILE}" ]; then
    echo "Error: ${IMAGE_FILE} not found in ${SCRIPT_DIR}"
    echo "Run build.sh first, then copy ${IMAGE_FILE} to this directory on the server."
    exit 1
fi

echo "Loading image from ${IMAGE_FILE} ..."
docker load < "${SCRIPT_DIR}/${IMAGE_FILE}"

echo ""
echo "Image loaded. Verify with:  docker images dicom-mcp"
echo ""
echo "Add this to your docker-compose.yaml:"
echo ""
echo "  dicom-mcp:"
echo "    image: dicom-mcp:latest"
echo "    restart: unless-stopped"
echo "    ports:"
echo '      - "127.0.0.1:8000:8000"'
echo "    volumes:"
echo "      - ./dicom-mcp/configuration.docker.yaml:/app/configuration.yaml:ro"
echo "      - ./dicom_downloads:/app/downloads"
echo "    depends_on:"
echo "      - orthanc"
echo ""
echo "Then run:  docker compose up -d dicom-mcp"
