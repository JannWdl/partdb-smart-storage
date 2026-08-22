#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

docker compose build smart-storage
docker compose up -d smart-storage

echo "Smart-Storage-Oberfläche wurde neu gebaut und gestartet."

