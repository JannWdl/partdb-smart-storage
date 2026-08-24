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
if [[ "${EUID:-$(id -u)}" -eq 0 ]] && command -v systemctl >/dev/null 2>&1; then
  ./scripts/ensure-autostart.sh
else
  docker compose up -d --remove-orphans
fi
./scripts/migrate-partdb.sh
docker image prune -f

echo "Update abgeschlossen."
