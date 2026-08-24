#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
SERVICE="partdb-smart-storage.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Bitte mit sudo starten: sudo ./scripts/ensure-autostart.sh"
  exit 1
fi

cd "$APP_DIR"

cp systemd/partdb-smart-storage.service "/etc/systemd/system/$SERVICE"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo
echo "Autostart ist aktiv."
systemctl --no-pager --full status "$SERVICE" || true
echo
docker compose ps
