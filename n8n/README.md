# n8n Telegram Workflow

Importiere `telegram-smart-storage.json` über die n8n-Weboberfläche.

Danach sind nur zwei Dinge zwingend einzustellen:

1. Im **Telegram Trigger** und in **Telegram Antwort senden** dasselbe Telegram-Credential mit dem BotFather-Token auswählen.
2. Im Node **⚙️ CONFIG HIER ÄNDERN** `smartStorageBaseUrl` auf die von n8n erreichbare Smart-Storage-URL setzen, z. B. `http://192.168.178.50:8090`.

Empfohlen: Danach `allowedTelegramUserIds` auf deine Telegram-User-ID setzen, damit nicht jeder Benutzer mit Zugriff auf den Bot Bestand ändern oder LEDs steuern kann.

Die vollständige Anleitung steht in [`docs/telegram-n8n.md`](../docs/telegram-n8n.md).
