#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
USERNAME="${PARTDB_ADMIN_USER:-admin}"
PASSWORD="${PARTDB_ADMIN_PASSWORD:-admin}"

if [[ -d "$APP_DIR" ]]; then
  cd "$APP_DIR"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker wurde nicht gefunden."
  exit 1
fi

if ! docker compose ps partdb >/dev/null 2>&1; then
  echo "Part-DB Container wurde nicht gefunden. Bitte zuerst installieren/starten."
  exit 1
fi

echo
echo "Part-DB Admin einrichten"
echo "Benutzer: $USERNAME"
echo "Passwort: $PASSWORD"

tmp_script="$(mktemp)"
tmp_input="$(mktemp)"
trap 'rm -f "$tmp_script" "$tmp_input"' EXIT
printf "yes\n%s\n%s\n" "$PASSWORD" "$PASSWORD" > "$tmp_input"

if ! docker compose exec -T --user www-data partdb php bin/console partdb:users:set-password "$USERNAME" < "$tmp_input"; then
  echo
  echo "Passwort konnte fuer '$USERNAME' nicht gesetzt werden."
  echo "Vorhandene Benutzer anzeigen:"
  echo "  sudo docker compose exec --user www-data partdb php bin/console partdb:users:list"
  exit 1
fi

cat > "$tmp_script" <<'PHP'
<?php
require '/var/www/html/vendor/autoload.php';

use App\Entity\UserSystem\ApiToken;
use App\Entity\UserSystem\ApiTokenLevel;
use App\Entity\UserSystem\User;
use App\Services\UserSystem\PermissionPresetsHelper;

$username = getenv('PARTDB_SETUP_USER') ?: 'admin';

$kernel = new App\Kernel(getenv('APP_ENV') ?: 'docker', false);
$kernel->boot();
$container = $kernel->getContainer();
$em = $container->get('doctrine')->getManager();
$repo = $em->getRepository(User::class);
$user = method_exists($repo, 'findByEmailOrName') ? $repo->findByEmailOrName($username) : null;

if (!$user instanceof User) {
    fwrite(STDERR, "User '$username' wurde nicht gefunden.\n");
    exit(2);
}

$user->setDisabled(false);

$presets = $container->get(PermissionPresetsHelper::class);
$presets->applyPreset($user, PermissionPresetsHelper::PRESET_ADMIN);

$token = null;
foreach ($user->getApiTokens() as $existing) {
    if ($existing->getName() === 'Smart Storage') {
        $token = $existing;
        break;
    }
}

if (!$token instanceof ApiToken) {
    $token = new ApiToken();
    $token->setName('Smart Storage');
    $token->setUser($user);
    $user->addApiToken($token);
    $em->persist($token);
}

$token->setLevel(ApiTokenLevel::FULL);
$token->setValidUntil(null);
$em->persist($user);
$em->flush();

echo $token->getToken() . PHP_EOL;
PHP

if ! token="$(
  docker compose exec -T \
    --user www-data \
    -e PARTDB_SETUP_USER="$USERNAME" \
    -e DATABASE_MYSQL_USE_SSL_CA=0 \
    -e DATABASE_MYSQL_SSL_VERIFY_CERT=0 \
    -e SAML_ENABLED=0 \
    partdb php < "$tmp_script"
)"; then
  echo
  echo "Admin-Zugang oder API-Token konnte nicht eingerichtet werden."
  echo "Vorhandene Benutzer anzeigen:"
  echo "  sudo docker compose exec --user www-data partdb php bin/console partdb:users:list"
  exit 1
fi

token="$(printf '%s' "$token" | tail -n 1 | tr -d '\r')"
if [[ -z "$token" ]]; then
  echo "Part-DB hat keinen API-Token ausgegeben."
  exit 1
fi

if [[ -f .env ]]; then
  if grep -q '^PARTDB_API_TOKEN=' .env; then
    sed -i "s|^PARTDB_API_TOKEN=.*|PARTDB_API_TOKEN=$token|" .env
  else
    printf '\nPARTDB_API_TOKEN=%s\n' "$token" >> .env
  fi
fi

docker compose up -d smart-storage >/dev/null
docker compose exec -T \
  -e PARTDB_API_TOKEN="$token" \
  smart-storage python - <<'PY'
import json
import os
import sqlite3
import time

db_path = "/data/smart-storage.db"
now = int(time.time())
con = sqlite3.connect(db_path)
try:
    con.execute("create table if not exists settings (key text primary key, value text not null, updated_at integer not null)")
    values = {
        "partdb_api_token": os.environ["PARTDB_API_TOKEN"],
        "partdb_internal_url": os.environ.get("PARTDB_INTERNAL_URL", "http://partdb:80").rstrip("/"),
        "partdb_url": os.environ.get("PARTDB_PUBLIC_URL", "http://partdb.local:8080").rstrip("/"),
        "partdb_stock_write_enabled": True,
    }
    for key, value in values.items():
        con.execute(
            """
            insert into settings (key, value, updated_at)
            values (?, ?, ?)
            on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value), now),
        )
    con.commit()
finally:
    con.close()
PY
docker compose restart smart-storage >/dev/null

api_status="$(curl -sS -o /dev/null -w "%{http_code}" \
  -H "Accept: application/ld+json" \
  -H "Authorization: Bearer $token" \
  http://localhost:8080/api/parts.jsonld || true)"

echo
echo "Admin-Zugang ist bereit."
echo "Login:    $USERNAME"
echo "Passwort: $PASSWORD"
echo "API:      Smart Storage Token wurde gespeichert. Teststatus: $api_status"
if [[ "$api_status" == "401" || "$api_status" == "403" ]]; then
  echo "Hinweis: Part-DB verweigert den API-Zugriff. In Part-DB Benutzerrechte Miscellaneous/API und Token-Scope pruefen."
fi
echo "Part-DB:  http://$(hostname -I | awk '{print $1}'):8080"
