# Telegram Bot mit n8n

Der Telegram-Bot ist nur die Bedienoberfläche. Bestand bleibt in Part-DB, Fachzuordnung und WLED bleiben in Smart Storage. Dadurch arbeiten Weboberfläche, CCV-Terminal und Telegram auf derselben Datenbasis.

## Funktionen

- Bestand per Name oder Part-DB-ID abfragen
- Teile suchen
- beliebige Mengen einlagern und entnehmen
- zugeordnetes Fach per WLED leuchten lassen
- belegte Fächer anzeigen
- letzte Buchungen anzeigen
- WLED ausschalten
- optional Telegram-Zugriff auf bestimmte Chat-IDs begrenzen

## Dateien

- `telegram-smart-storage.workflow.json` – direkt in n8n importierbarer Workflow
- `../app/telegram_api.py` – kleine API-Erweiterung des Smart-Storage-Backends

## 1. Smart Storage aktualisieren

Nach dem Merge/Update auf dem Raspberry Pi:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/update.sh
```

Oder nur die App neu bauen:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/reload-app.sh
```

Danach steht zusätzlich bereit:

```text
POST http://<PI-IP>:8090/api/telegram/action
```

Beispiel:

```bash
curl -X POST http://127.0.0.1:8090/api/telegram/action \
  -H 'Content-Type: application/json' \
  -d '{"action":"stock","query":"M3 Schraube","quantity":1}'
```

## 2. Telegram-Bot anlegen

1. In Telegram `@BotFather` öffnen.
2. `/newbot` ausführen.
3. Namen und Benutzernamen vergeben.
4. Bot-Token kopieren.
5. In n8n unter **Credentials** ein neues **Telegram API** Credential anlegen und den Token eintragen.

Sinnvolle BotFather-Kommandos für `/setcommands`:

```text
bestand - Bestand anzeigen
plus - Menge einlagern
minus - Menge entnehmen
licht - Fach leuchten lassen
suche - Teile suchen
faecher - belegte Fächer anzeigen
events - letzte Buchungen anzeigen
aus - Lagerbeleuchtung ausschalten
hilfe - Hilfe anzeigen
```

## 3. Workflow importieren

In n8n:

1. **Workflows** öffnen.
2. **Import from File** auswählen.
3. `n8n/telegram-smart-storage.workflow.json` importieren.
4. Im Node **Telegram Trigger** das Telegram-Credential auswählen.
5. Im Node **Telegram Antwort** dasselbe Credential auswählen.
6. Node **⚙️ KONFIGURATION** öffnen.
7. `smartStorageUrl` setzen.
8. Optional `allowedChatIds` setzen.
9. Workflow aktivieren.

### `smartStorageUrl`

Wenn n8n im selben LAN, aber in einem anderen Container/Host läuft:

```text
http://<PI-IP>:8090
```

Wenn n8n im selben Docker-Compose-Netz wie Smart Storage läuft:

```text
http://smart-storage:8090
```

`127.0.0.1` nur verwenden, wenn n8n wirklich im selben Netzwerk-Namespace wie Smart Storage läuft. In einem eigenen Docker-Container zeigt `127.0.0.1` auf den n8n-Container selbst.

### `allowedChatIds`

Leer lassen, wenn der Bot für alle Chats reagieren darf. Für einen privaten Bot besser die eigene Chat-ID eintragen. Mehrere IDs werden mit Komma getrennt:

```text
123456789,987654321
```

Die eigene Chat-ID sieht man nach einem Testlauf im Output des **Telegram Trigger** unter `message.chat.id`.

## 4. Befehle

```text
/bestand M3 Schraube
/bestand 42
/plus M3 Schraube 10
/minus 42 2
/licht Widerstand 10k
/suche ESP32
/faecher
/events
/aus
/hilfe
```

Normaler Text ohne Slash wird als Bestandsabfrage behandelt:

```text
M3 Schraube
```

## Wo soll n8n laufen?

### Vorhandenes n8n im LAN

Das ist die einfachste Variante. Workflow importieren und `smartStorageUrl` auf die IP des Raspberry Pi setzen.

### n8n direkt auf dem Raspberry Pi

Das funktioniert ebenfalls. Für einen Telegram Trigger muss n8n jedoch über eine von Telegram erreichbare **HTTPS-Webhook-URL** verfügen. Bei Self-Hosting also Reverse Proxy oder Tunnel verwenden und `WEBHOOK_URL` in n8n korrekt setzen.

Typische n8n-Variablen:

```env
N8N_HOST=n8n.example.de
N8N_PROTOCOL=https
WEBHOOK_URL=https://n8n.example.de/
GENERIC_TIMEZONE=Europe/Berlin
TZ=Europe/Berlin
```

Wenn bereits eine n8n-Instanz mit funktionierenden Telegram-Webhooks existiert, ist es normalerweise sinnvoller, diese weiterzuverwenden.

## Architektur

```text
Telegram
   |
   v
n8n Telegram Trigger
   |
   v
POST /api/telegram/action
   |
   +--> Part-DB Bestand
   +--> Smart-Storage Zuordnungen
   +--> WLED Fachbeleuchtung
   +--> stock_events Historie
```

n8n benötigt dadurch keinen Part-DB-API-Token. Der Token bleibt ausschließlich im Smart-Storage-Backend.

## Sicherheit

- Port `8090` nicht direkt ins Internet weiterleiten.
- n8n und Smart Storage nach Möglichkeit im gleichen LAN/VPN betreiben.
- `allowedChatIds` für einen privaten Bot setzen.
- Telegram-Bot-Token ausschließlich als n8n-Credential speichern, nicht im Workflow-JSON oder Git-Repository.
