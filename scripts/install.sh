#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/partdb-smart-storage"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Bitte mit sudo starten: sudo ./scripts/install.sh"
  exit 1
fi

if ! grep -qi "raspberry pi\|debian\|ubuntu" /etc/os-release; then
  echo "Hinweis: Dieses Skript ist für Raspberry Pi OS 64-bit/Debian gebaut."
fi

apt-get update
apt-get install -y ca-certificates curl git openssl rsync

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

install -d -m 0755 "$APP_DIR"
rsync -a --delete \
  --exclude data \
  --exclude backups \
  "$REPO_DIR/" "$APP_DIR/"

cd "$APP_DIR"
if [[ ! -f .env ]]; then
  cp .env.example .env
  secret="$(./scripts/generate-secret.sh)"
  printf '\nAPP_SECRET=%s\n' "$secret" >> .env
fi

install -d -m 0755 data/partdb/db data/partdb/uploads data/partdb/public_media data/smart-storage backups
docker compose pull
docker compose build
./scripts/ensure-autostart.sh
sleep 8
./scripts/migrate-partdb.sh
PARTDB_SET_ADMIN_PASSWORD=1 ./scripts/setup-partdb-admin.sh

echo
echo "Fertig."
echo "Part-DB:        http://$(hostname -I | awk '{print $1}'):8080"
echo "Smart Storage:  http://$(hostname -I | awk '{print $1}'):8090"
echo "Part-DB Login:  admin / admin"
echo "Konfiguration:  $APP_DIR/.env"
