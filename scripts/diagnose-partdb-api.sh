#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
cd "$APP_DIR"

echo "Part-DB API Diagnose"
echo

env_token=""
if [[ -f .env ]]; then
  env_token="$(grep '^PARTDB_API_TOKEN=' .env | tail -n 1 | cut -d= -f2- || true)"
fi

echo ".env Token-Laenge: ${#env_token}"
if [[ -z "$env_token" ]]; then
  echo ".env: PARTDB_API_TOKEN ist leer."
else
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  status="$(curl -sS -o "$tmp" -w "%{http_code}" \
    -H "Accept: application/ld+json" \
    -H "Authorization: Bearer $env_token" \
    http://localhost:8080/api/parts.jsonld || true)"
  echo ".env Token HTTP-Status: $status"
  if [[ "$status" != "200" ]]; then
    echo ".env Token Antwort:"
    head -c 800 "$tmp"
    echo
  fi
fi

echo
echo "Smart-Storage gespeicherter Token:"
docker compose exec -T smart-storage python - <<'PY'
import json
import sqlite3

import requests

db_path = "/data/smart-storage.db"
token = ""
try:
    con = sqlite3.connect(db_path)
    row = con.execute("select value from settings where key='partdb_api_token'").fetchone()
    if row:
        token = json.loads(row[0])
finally:
    try:
        con.close()
    except Exception:
        pass

print(f"DB Token-Laenge: {len(token)}")
if not token:
    print("DB: partdb_api_token ist leer.")
    raise SystemExit(0)

try:
    response = requests.get(
        "http://partdb:80/api/parts.jsonld",
        headers={"Accept": "application/ld+json", "Authorization": f"Bearer {token}"},
        timeout=12,
    )
    print(f"DB Token HTTP-Status: {response.status_code}")
    if response.status_code != 200:
        print("DB Token Antwort:")
        print(response.text[:800])
except Exception as exc:
    print(f"DB Token Testfehler: {exc}")
PY

echo
echo "Hinweis:"
echo "- HTTP 200: Token und API-Rechte sind ok."
echo "- HTTP 401/403: In Part-DB Benutzerrechte Miscellaneous/API und Token-Scope pruefen."
echo "- Token-Laenge 0: Token fehlt in .env oder Smart Storage."
