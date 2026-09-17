# Telegram Bot mit n8n

Der Telegram-Bot ist ein Frontend für die bestehende Smart-Storage-API. Es gibt keine zweite Lagerdatenbank in n8n: Part-DB bleibt für den Bestand zuständig, Smart Storage für Fachzuordnung, LEDs/WLED und Buchungsprotokoll.

## Funktionen

Der Workflow `n8n/telegram-smart-storage.json` bietet Buttons und Befehle für:

- Part-DB durchsuchen
- aktuellen Part-DB-Bestand eines Teils lesen
- Lagerliste mit Fach und aktuellem Bestand anzeigen
- beliebige Mengen einlagern und entnehmen
- Part-DB-Teil einem Smart-Storage-Fach zuordnen
- Teil suchen und das zugehörige Fach über WLED leuchten lassen
- Fächer/LED-Bereiche anzeigen
- letzte Buchungen anzeigen
- Part-DB/WLED-Status prüfen
- WLED ausschalten

Die Befehle sind zusätzlich direkt nutzbar:

```text
/start
/help
/search ESP32
/stock 42
/inventory
/add 42 5
/remove 42 2
/assign 42 cabinet-1-r1-c2 ESP32 DevKit
/locate ESP32
/slots
/events
/status
/off
```

Freitext ohne `/` wird als Part-DB-Suche behandelt.

## 1. Smart Storage aktualisieren

Die Telegram-Integration verwendet zusätzliche API-Endpunkte aus `app/api_extensions.py`. Der Docker-Container lädt diese Erweiterung automatisch.

Auf dem Raspberry Pi bzw. Smart-Storage-Host:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/update.sh
```

Alternativ nach einem manuellen `git pull`:

```bash
sudo ./scripts/reload-app.sh
```

Danach prüfen:

```bash
curl http://127.0.0.1:8090/api/health
```

Zusätzliche Endpunkte:

```text
GET  /api/parts/{part_id}/summary
GET  /api/inventory?limit=50
POST /api/stock/change
```

Beispiel für eine Mengenbuchung:

```json
{
  "partdb_part_id": "42",
  "action": "ADD",
  "quantity": 5
}
```

Die Buchung verwendet dieselbe Part-DB- und `stock_events`-Logik wie das vorhandene ZVT-Terminal.

## 2. Telegram Bot anlegen

1. In Telegram `@BotFather` öffnen.
2. `/newbot` senden.
3. Namen und Benutzernamen vergeben.
4. Den ausgegebenen Bot-Token kopieren.

Den Token nicht in Git oder in den Workflow schreiben.

## 3. Workflow in n8n importieren

1. n8n öffnen.
2. **Workflows -> Import from File** wählen.
3. `n8n/telegram-smart-storage.json` importieren.
4. Im Node **Telegram Trigger** ein neues Telegram-Credential mit dem BotFather-Token anlegen.
5. Dasselbe Credential im Node **Telegram Antwort senden** auswählen.
6. Den Node **⚙️ CONFIG HIER ÄNDERN** öffnen.
7. `smartStorageBaseUrl` auf die aus Sicht von n8n erreichbare Smart-Storage-URL setzen, zum Beispiel `http://192.168.178.50:8090`.
8. Optional `allowedTelegramUserIds` setzen. Mehrere IDs kommasepariert, zum Beispiel `123456789,987654321`. Leer bedeutet: jeder Benutzer, der den Bot erreicht, darf das Lager steuern.
9. Workflow speichern und aktivieren.

Die Telegram-User-ID steht in einem Test-Event des Telegram-Triggers unter `message.from.id` bzw. bei Buttons unter `callback_query.from.id`.

## 4. Wo n8n laufen kann

n8n muss nicht im Smart-Storage-Container laufen. Es reicht, wenn n8n die Smart-Storage-API auf Port `8090` erreichen kann.

### n8n auf demselben Raspberry Pi

Smart Storage kann beispielsweise über die LAN-IP des Pi angesprochen werden:

```text
http://192.168.178.x:8090
```

### n8n auf einem anderen Server / Proxmox

Auch hier einfach die LAN-IP oder einen internen DNS-Namen des Smart-Storage-Hosts verwenden. Port `8090` muss zwischen n8n und Smart Storage erreichbar sein.

Smart Storage selbst sollte nicht direkt ins Internet veröffentlicht werden. Der Telegram-Bot spricht von n8n aus intern mit der API.

## 5. Telegram Webhook / HTTPS

Der **Telegram Trigger** arbeitet mit einem Telegram-Webhook. Deshalb muss Telegram die Webhook-URL deiner n8n-Instanz über HTTPS erreichen können.

Wenn n8n nur im LAN läuft, brauchst du für n8n eine öffentliche HTTPS-Adresse, zum Beispiel über deinen vorhandenen Reverse Proxy oder einen Cloudflare Tunnel. Bei Self-Hosted-n8n muss `WEBHOOK_URL` auf diese externe Basis-URL zeigen, z. B.:

```env
WEBHOOK_URL=https://n8n.example.de/
N8N_PROTOCOL=https
GENERIC_TIMEZONE=Europe/Berlin
TZ=Europe/Berlin
```

Die Smart-Storage-URL im Workflow bleibt trotzdem die interne LAN-URL.

## 6. Sicherheit

Der Bot kann echten Part-DB-Bestand verändern. Deshalb:

- `allowedTelegramUserIds` nach dem ersten Test setzen.
- Bot-Token ausschließlich als n8n-Credential speichern.
- Port `8090` nur intern erreichbar lassen.
- Part-DB-API-Token nicht in n8n kopieren; der Workflow benutzt ausschließlich die Smart-Storage-API.
- Vor produktiven Tests zuerst mit kleinen Mengen arbeiten.

Wenn `PARTDB_STOCK_WRITE_ENABLED=false` gesetzt ist, meldet der Bot den vorhandenen Smart-Storage-Testmodus und verändert Part-DB nicht.

## 7. Datenfluss

```text
Telegram
   |
   v
n8n Telegram Trigger
   |
   v
Smart Storage API :8090
   |             |
   |             +--> WLED -> Fach leuchten
   |
   +--> Part-DB API -> Bestand lesen / buchen
   |
   +--> SQLite -> Zuordnungen + stock_events
```

Damit bleiben Weboberfläche, Barcode-Scanner, CCV/ZVT und Telegram auf derselben Lagerlogik.
