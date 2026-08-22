#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
BACKUP="${1:-}"

if [[ -z "$BACKUP" || ! -f "$BACKUP" ]]; then
  echo "Nutzung: sudo ./scripts/restore.sh /pfad/zum/backup.tar.gz"
  exit 1
fi

cd "$APP_DIR"
docker compose down
tar -xzf "$BACKUP" -C "$APP_DIR"
docker compose up -d

echo "Restore abgeschlossen."

