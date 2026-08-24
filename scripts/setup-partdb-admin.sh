#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/partdb-smart-storage}"
USERNAME="${PARTDB_ADMIN_USER:-admin}"

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
echo

read -r -s -p "Neues Part-DB Passwort: " password
echo
read -r -s -p "Passwort wiederholen: " password_repeat
echo

if [[ -z "$password" ]]; then
  echo "Passwort darf nicht leer sein."
  exit 1
fi

if [[ "$password" != "$password_repeat" ]]; then
  echo "Passwoerter stimmen nicht ueberein."
  exit 1
fi

tmp_input="$(mktemp)"
trap 'rm -f "$tmp_input"' EXIT
printf "yes\n%s\n%s\n" "$password" "$password" > "$tmp_input"

if ! docker compose exec -T partdb php bin/console partdb:users:set-password "$USERNAME" < "$tmp_input"; then
  echo
  echo "Passwort konnte fuer '$USERNAME' nicht gesetzt werden."
  echo "Vorhandene Benutzer anzeigen:"
  echo "  sudo docker compose exec partdb php bin/console partdb:users:list"
  exit 1
fi

echo
echo "Admin-Zugang ist bereit."
echo "Login:    $USERNAME"
echo "Part-DB:  http://$(hostname -I | awk '{print $1}'):8080"
