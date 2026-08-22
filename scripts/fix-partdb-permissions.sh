#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

docker compose exec -T partdb sh -lc '
  mkdir -p var/cache var/log var/db uploads public/media
  chown -R www-data:www-data var/cache var/log var/db uploads public/media
  find var/cache var/log var/db uploads public/media -type d -exec chmod 775 {} \;
  find var/cache var/log var/db uploads public/media -type f -exec chmod 664 {} \;
'

echo "Part-DB Dateirechte wurden repariert."

