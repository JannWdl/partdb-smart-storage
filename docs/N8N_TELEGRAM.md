# Telegram Bot mit n8n

Dieser Workflow macht Telegram zur Fernbedienung für Smart Storage:

- Bestand erhöhen oder senken
- Teile suchen
- Fächer leuchten lassen
- Nachkauf markieren
- letzte Buchungen anzeigen

Die Lagerlogik läuft in Smart Storage. n8n nimmt nur Telegram-Nachrichten an und leitet sie an die Smart-Storage-API weiter.

## 1. Telegram Bot erstellen

1. In Telegram `@BotFather` öffnen.
2. `/newbot` senden.
3. Namen und Bot-Username vergeben.
4. Den Bot-Token kopieren.

Den Token brauchst du gleich in n8n als Telegram-Credential.

## 2. n8n auf dem Raspberry Pi starten

Wenn n8n direkt mit diesem Projekt auf dem Pi laufen soll:

```bash
cd /opt/partdb-smart-storage
sudo git pull
sudo ./scripts/fix-n8n-permissions.sh
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d n8n
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml ps
```

Warte danach etwa 20 bis 60 Sekunden, bis `partdb-smart-storage-n8n` als `Up` angezeigt wird. Danach n8n öffnen:

```text
http://<pi-ip>:5678
```

Beim ersten Öffnen erstellt n8n einen eigenen n8n-Account. Das ist nur für n8n, nicht für Part-DB.

## 3. n8n auf einem anderen Server nutzen

Wenn du schon ein anderes n8n hast, brauchst du den n8n-Container auf dem Pi nicht.

Setze im Workflow die Smart-Storage-URL auf:

```text
http://<pi-ip>:8090
```

Wenn n8n im gleichen Docker-Compose wie Smart Storage läuft, passt diese interne URL:

```text
http://smart-storage:8090
```

## 4. Workflow importieren

Für lokales n8n auf dem Raspberry Pi importierst du die Polling-Variante. Sie braucht keinen öffentlichen HTTPS-Webhook.

In n8n:

1. `Workflows` öffnen.
2. `Import from File` wählen.
3. Diese Datei importieren:

```text
n8n/telegram-smart-storage-polling.json
```

4. Den Node `CONFIG HIER ÄNDERN` öffnen.
5. Bei `telegramBotToken` den BotFather-Token eintragen.
6. `smartStorageBaseUrl` prüfen. Bei n8n aus diesem Docker Compose passt `http://smart-storage:8090`.
7. Workflow speichern und aktivieren.

Die Datei `n8n/telegram-smart-storage.json` ist die Webhook-Variante mit `Telegram Trigger`. Diese Variante funktioniert nur, wenn n8n öffentlich per HTTPS erreichbar ist. Auf einem lokalen Pi kommt sonst beim Aktivieren `Bad request - please check your parameters`.

## 5. Smart-Storage-URL prüfen

Der Polling-Workflow nutzt standardmäßig:

```text
http://smart-storage:8090
```

Auf dem Pi mit `docker-compose.n8n.yml` ist das richtig.

Bei externem n8n trägst du im Node stattdessen direkt ein:

```text
http://<pi-ip>:8090/api/telegram/command
```

## Befehle

```text
/help
/status
/suche 10k
/find 10k
/fach 1
/add 123 1
/remove 123 1
/wishlist 123
/events
```

Beispiele:

```text
/suche widerstand
/find widerstand 10k
/fach magazin-1-r1-c1
/add 123 5
/remove 123 2
/wishlist 123
```

`/add` und `/remove` schreiben in Part-DB, wenn in Smart Storage `Part-DB Bestand schreiben` aktiv ist. Ist der Schalter aus, wird nur lokal protokolliert.

## Sicherheit

- Der Bot-Token gehört nur in n8n, nicht in Git.
- Teile den Bot nicht öffentlich.
- Wenn mehrere Leute Zugriff haben, lege in Telegram eine private Gruppe mit dem Bot an.
- Smart Storage sollte im Heimnetz bleiben und nicht direkt ins Internet freigegeben werden.

## Fehlerdiagnose

Smart Storage erreichbar?

```bash
curl http://<pi-ip>:8090/api/health
```

n8n läuft?

```bash
cd /opt/partdb-smart-storage
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml ps
```

Wenn `ps` den Container als `Up` zeigt, aber der Browser noch nicht lädt, warte kurz und öffne die Seite erneut. Beim ersten Start erzeugt n8n erst seine lokale Konfiguration.

Direkt auf dem Pi testen:

```bash
curl -I http://localhost:5678
```

Wenn im Log `EACCES: permission denied, open '/home/node/.n8n/config'` steht:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/fix-n8n-permissions.sh
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d n8n
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml ps
```

Workflow-Ausführungen findest du in n8n unter `Executions`.
