#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
N8N_DIR="$PROJECT_DIR/data/n8n"

echo "n8n-Rechte reparieren"
mkdir -p "$N8N_DIR"
chown -R 1000:1000 "$N8N_DIR"
chmod -R u+rwX,g+rwX "$N8N_DIR"

echo "OK: $N8N_DIR gehört jetzt dem n8n-Container-Benutzer 1000:1000."
echo "Starte n8n danach neu mit:"
echo "sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d n8n"
