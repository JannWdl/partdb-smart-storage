#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Bitte mit sudo starten."
  exit 1
fi

cd "$APP_DIR"
./scripts/backup.sh || true
docker compose down
systemctl disable --now partdb-smart-storage.service 2>/dev/null || true
rm -f /etc/systemd/system/partdb-smart-storage.service
systemctl daemon-reload

echo "Dienst entfernt. Daten liegen weiterhin in $APP_DIR."
echo "Zum vollstaendigen Entfernen nach Kontrolle ausfuehren: sudo rm -rf $APP_DIR"

