#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

docker compose exec -T partdb php bin/console doctrine:migrations:migrate --no-interaction
docker compose exec -T partdb php bin/console cache:clear
docker compose exec -T partdb php bin/console cache:pool:clear --all
docker compose restart partdb

echo "Part-DB Datenbankschema ist aktualisiert."

