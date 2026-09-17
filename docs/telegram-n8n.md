# Telegram Bot mit n8n

Der Telegram-Bot ist ein Frontend für die bestehende Smart-Storage-API. Es gibt keine zweite Lagerdatenbank in n8n: Part-DB bleibt für den Bestand zuständig, Smart Storage für Fachzuordnung, LEDs/WLED und Buchungsprotokoll.

## Funktionen

Der lokale Workflow `n8n/telegram-smart-storage-polling.json` bietet Befehle für:

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

Für n8n auf dem Raspberry Pi oder in deinem LAN nimmst du die Polling-Variante:

1. n8n öffnen.
2. **Workflows -> Import from File** wählen.
3. `n8n/telegram-smart-storage-polling.json` importieren.
4. Den Node **CONFIG HIER ÄNDERN** öffnen.
5. Bei `telegramBotToken` den BotFather-Token eintragen.
6. `smartStorageBaseUrl` prüfen:
   - n8n aus `docker-compose.n8n.yml`: `http://smart-storage:8090`
   - externes n8n: `http://<pi-ip>:8090`
7. Optional `allowedTelegramUserIds` setzen. Mehrere IDs kommasepariert, zum Beispiel `123456789,987654321`. Leer bedeutet: jeder Benutzer, der den Bot erreicht, darf das Lager steuern.
8. Workflow speichern und aktivieren.

Diese Polling-Variante braucht kein Telegram-Credential in n8n und keinen öffentlichen HTTPS-Webhook.

Die Telegram-User-ID zeigt der Bot an, wenn ein nicht freigegebener Benutzer schreibt. Alternativ kannst du sie über `@userinfobot` in Telegram auslesen.

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

Die Datei `n8n/telegram-smart-storage.json` ist die Webhook-Variante mit **Telegram Trigger**. Sie ist nur sinnvoll, wenn deine n8n-Instanz öffentlich per HTTPS erreichbar ist.

Der **Telegram Trigger** arbeitet mit einem Telegram-Webhook. Deshalb muss Telegram die Webhook-URL deiner n8n-Instanz über HTTPS erreichen können.

Wenn n8n nur lokal auf dem Pi läuft, nimm stattdessen `n8n/telegram-smart-storage-polling.json`. Sonst erscheint beim Aktivieren:

```text
Workflow could not be published
Error in node "Telegram Trigger":
Bad request - please check your parameters
```

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
n8n Polling Workflow
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
