# n8n Telegram Workflows

Für den Raspberry Pi im Heimnetz importierst du normalerweise:

```text
telegram-smart-storage-polling.json
```

Dieser Workflow braucht keinen öffentlichen HTTPS-Webhook und lässt sich auf lokalem n8n direkt aktivieren.

Danach sind nur zwei Dinge zwingend einzustellen:

1. Im Node **CONFIG HIER ÄNDERN** den BotFather-Token bei `telegramBotToken` eintragen.
2. `smartStorageBaseUrl` prüfen. Wenn n8n aus `docker-compose.n8n.yml` läuft, passt `http://smart-storage:8090`.

Empfohlen: Danach `allowedTelegramUserIds` auf deine Telegram-User-ID setzen, damit nicht jeder Benutzer mit Zugriff auf den Bot Bestand ändern oder LEDs steuern kann.

Die Datei `telegram-smart-storage.json` ist die Webhook-Variante mit **Telegram Trigger**. Diese Variante braucht eine öffentlich erreichbare HTTPS-URL für n8n. Auf einem lokalen Pi ohne HTTPS schlägt das Aktivieren mit `Bad request - please check your parameters` fehl.

Die vollständige Anleitung steht in [`docs/telegram-n8n.md`](../docs/telegram-n8n.md).
