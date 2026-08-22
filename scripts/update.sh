#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

./scripts/backup.sh
docker compose pull
docker compose build --pull
docker compose up -d
docker image prune -f

echo "Update abgeschlossen."

