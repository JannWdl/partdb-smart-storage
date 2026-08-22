#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

./scripts/fix-partdb-permissions.sh
docker compose exec -T --user www-data partdb php bin/console doctrine:migrations:migrate --no-interaction
docker compose exec -T --user www-data partdb php bin/console cache:clear
docker compose exec -T --user www-data partdb php bin/console cache:pool:clear --all
./scripts/fix-partdb-permissions.sh
docker compose restart partdb

echo "Part-DB Datenbankschema ist aktualisiert."
