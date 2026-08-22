#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

./scripts/backup.sh
if [[ -d .git ]]; then
  git pull --ff-only
fi
docker compose pull
docker compose build --pull
docker compose up -d
./scripts/migrate-partdb.sh
docker image prune -f

echo "Update abgeschlossen."
