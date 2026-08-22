#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups
docker compose pause >/dev/null 2>&1 || true
tar -czf "backups/partdb-smart-storage-${stamp}.tar.gz" data .env config
docker compose unpause >/dev/null 2>&1 || true

echo "Backup erstellt: $APP_DIR/backups/partdb-smart-storage-${stamp}.tar.gz"

