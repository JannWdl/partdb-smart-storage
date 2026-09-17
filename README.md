# Part-DB Smart Storage

Reproduzierbares Raspberry-Pi-Projekt für Part-DB, WLED und ein visuelles Kleinteilemagazin.

Status: **Beta**. Die Grundfunktionen laufen, Part-DB-Stock-API und Barcode-Flows werden aktiv getestet.

## Funktionen

- Installiert Part-DB per Docker Compose auf Raspberry Pi OS 64-bit.
- Startet eine eigene Weboberfläche auf Port `8090`.
- Konfiguriert Magazine visuell: Reihen, Spalten, Start-LED, LEDs pro Fach, Strip-Verlauf und Serpentine.
- Berechnet LED-Bereiche automatisch pro Fach.
- Speichert Teil-zu-Fach-Zuordnungen in einer eigenen SQLite-Datenbank.
- Sucht Teile in Part-DB, sofern die Part-DB-API erreichbar ist.
- Testet einzelne Fächer direkt am WLED-Controller.
- Verwaltet Part-DB-, WLED- und Barcode-Einstellungen in der Oberfläche.
- Unterstützt USB-Barcode-Scanner und Browser-Kamera-Scanner.
- Bucht Barcode-Zugang/-Abgang in Part-DB und protokolliert alle Aktionen lokal.
- Bietet Locate-Suche: Teil suchen, passendes Fach leuchtet.
- Enthält Install, Update, Backup, Restore und Uninstall.
- Läuft nach Installation automatisch über systemd.

## Zielarchitektur

```text
Raspberry Pi OS 64-bit
  Docker Compose
    Part-DB                 http://pi:8080
      SQLite-Datenbank      ./data/partdb/db/app.db
    Smart Storage Web-App   http://pi:8090
      Config-DB             ./data/smart-storage/smart-storage.db
      WLED API              http://192.168.178.220/json/state
    n8n optional            http://pi:5678
      Telegram Bot          Workflow importierbar über n8n
```

## Schnellstart

Auf einem frischen Raspberry Pi:

```bash
sudo apt-get install git -y 
git clone https://github.com/JannWdl/partdb-smart-storage.git
cd partdb-smart-storage
sudo ./scripts/install.sh
```

Danach:

- Part-DB: `http://<pi-ip>:8080`
- Smart Storage: `http://<pi-ip>:8090`
- Part-DB Login nach Erstinstallation: `admin` / `admin`

Der Installer setzt das Admin-Passwort nur bei der Erstinstallation auf `admin`. Danach verbindet er Smart Storage automatisch mit Part-DB, indem er API-Rechte für den Admin setzt, einen API-Token erzeugt und diesen in Smart Storage hinterlegt.

## Autostart Als Service

Die Installation richtet einen systemd-Service ein. Dieser startet beim Raspberry-Pi-Neustart den kompletten Docker-Compose-Stack:

- Part-DB auf Port `8080`
- Smart Storage auf Port `8090`
- gemeinsame Docker-Netzwerkverbindung für die interne Part-DB-API

Prüfen:

```bash
sudo systemctl status partdb-smart-storage
cd /opt/partdb-smart-storage
sudo docker compose ps
```

Autostart reparieren oder nach einem manuellen Update neu setzen:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/ensure-autostart.sh
```

Manuell steuern:

```bash
sudo systemctl start partdb-smart-storage
sudo systemctl stop partdb-smart-storage
sudo systemctl restart partdb-smart-storage
```

Wenn Part-DB schon installiert ist und nur Admin/API-Anbindung repariert werden soll:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/setup-partdb-admin.sh
```

Dieser Reparaturlauf ändert das vorhandene Admin-Passwort nicht.

## Konfiguration

Die wichtigste Datei ist nach der Installation:

```bash
/opt/partdb-smart-storage/.env
```

Wichtige Werte:

```env
PARTDB_PUBLIC_URL=http://partdb.local:8080
PARTDB_INTERNAL_URL=http://partdb:80
PARTDB_API_TOKEN=
WLED_BASE_URL=http://192.168.178.220
BARCODE_ENABLED=true
BARCODE_CAMERA_ENABLED=true
PARTDB_STOCK_WRITE_ENABLED=true
SCAN_TIMEOUT_SECONDS=30
APP_PORT=8090
PARTDB_PORT=8080
```

Diese Werte dienen als Startwerte. Nach der Installation können Part-DB-URL, WLED-URL und Barcode-Schalter direkt in der Smart-Storage-Oberfläche geändert werden. Wenn Part-DB ohne API-Token läuft, kann die App trotzdem lokale Zuordnungen und Buchungen verwalten.

Nach Änderungen:

```bash
cd /opt/partdb-smart-storage
docker compose up -d
```

## Magazinlayout

Das Standardlayout ist für ein typisches Kleinteilemagazin vorkonfiguriert:

- 5 Reihen
- 4 Spalten
- 4 LEDs pro kleinem Fach
- ein großes Fach unten mit 16 LEDs
- insgesamt 96 LEDs

Das Layout kann in der Weboberfläche geändert werden. Intern liegt es unter:

```bash
/opt/partdb-smart-storage/data/smart-storage/layout.json
```

Eine Beispielkonfiguration liegt in `config/example-layout.json`.

## Bedienung

1. Part-DB öffnen und Teile anlegen.
2. Smart Storage öffnen.
3. Teil über die Part-DB-Suche suchen.
4. Fach auswählen.
5. `Speichern & testen` klicken.
6. Das Fach leuchtet am WLED-Controller.

Später reicht die Suche oben links: Teilname eingeben, `Suchen & leuchten` klicken.

## Barcode

Das Barcode-Modul ist optional. Unterstützt werden USB-Scanner als Tastatureingabe, manuelle Eingabe und Browser-Kamera-Scanner, sofern der Browser `BarcodeDetector` unterstützt. USB-Scanner mit deutscher Tastaturbelegung werden automatisch korrigiert, zum Beispiel `PARTÖ123` zu `PART:123`.

Standardcodes:

- `PART:<partdb_id>` wählt ein Teil.
- `DRAWER:<drawer_id>` wählt ein Fach.
- `ADD` bucht Zugang.
- `REMOVE` bucht Abgang.
- `WISHLIST` markiert lokal Nachkauf/Wunschliste.
- `CANCEL` beendet die aktuelle Scan-Session.

Wenn `Part-DB Bestand schreiben` aktiv ist, ändern `ADD` und `REMOVE` den Bestand in Part-DB. Wenn der Schalter aus ist, läuft der Barcode-Flow als lokaler Testmodus. Die aktuelle Scan-Session läuft standardmäßig nach 30 Sekunden ab. Erfolg wird grün signalisiert, Fehler rot, Wunschliste blau und Locate gelb.

## Telegram Bot mit n8n

Optional kann n8n als Telegram-Fernbedienung für Smart Storage laufen. Damit kannst du per Telegram Teile suchen, Fächer leuchten lassen, Bestand erhöhen/senken und Buchungen anzeigen.

n8n auf dem Pi starten:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/fix-n8n-permissions.sh
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d n8n
sudo docker compose -f docker-compose.yml -f docker-compose.n8n.yml ps
```

Danach n8n öffnen:

```text
http://<pi-ip>:5678
```

In n8n den Workflow importieren:

```text
n8n/telegram-smart-storage.workflow.json
```

Wichtige Bot-Befehle:

```text
/status
/suche 10k
/find 10k
/fach 1
/add 123 1
/remove 123 1
/wishlist 123
/events
```

Die komplette Einrichtung steht in [docs/N8N_TELEGRAM.md](docs/N8N_TELEGRAM.md).

## WLED und Setup

Der Setup-Assistent berechnet die LEDs als fortlaufenden Stripe, nicht als Matrix:

- `Strip-Verlauf` legt nur fest, ob der Stripe Reihe für Reihe oder Spalte für Spalte durch die Fächer läuft.
- `Serpentine` aktivieren, wenn der Stripe am Ende jeder Reihe oder Spalte zurückläuft.
- Im Test-Schritt kann jedes Fach direkt am WLED-Controller leuchten.

Die WLED-URL wird in den Einstellungen gesetzt und kann dort direkt getestet werden.

Zum Testen ohne Raspberry-Pi-Flash gibt es eine standalone Browser-Seite:

```text
docs/browser-wled-test.html
```

Diese Datei kann direkt am PC im Browser geöffnet werden. Sie braucht weder Docker noch Backend.

## Wartung

Update:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/update.sh
```

Wenn das Projekt aus Git installiert wurde, holt `update.sh` automatisch den aktuellen Stand von GitHub. Bestehende Daten unter `data/`, Backups und `.env` bleiben erhalten.

Part-DB-Datenbankschema manuell aktualisieren:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/migrate-partdb.sh
```

Part-DB-Dateirechte reparieren, falls Part-DB mit einem Cache-/Permission-Fehler startet:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/fix-partdb-permissions.sh
sudo docker compose restart partdb
```

Nur die Smart-Storage-Oberfläche nach lokalen Änderungen neu bauen:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/reload-app.sh
```

Das ist der schnellste Weg zum Testen auf einem bereits installierten Raspberry Pi. Dabei wird kein neues Raspberry-Pi-Image erstellt und kein vollständiges Update ausgeführt. Der Setup-Assistent ist grafisch: Magazinblöcke werden auf einer Arbeitsfläche verschoben, ausgewählt und anschließend gespeichert.

Autostart für Part-DB und Smart Storage neu setzen:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/ensure-autostart.sh
```

Part-DB-API prüfen:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/diagnose-partdb-api.sh
```

Ziel ist bei `.env Token HTTP-Status` und `DB Token HTTP-Status` jeweils `200`. Bei `403` fehlen in Part-DB API-Rechte; `setup-partdb-admin.sh` setzt diese automatisch neu, ohne das Admin-Passwort zu ändern.

Backup:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/backup.sh
```

Restore:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/restore.sh backups/partdb-smart-storage-YYYYMMDD-HHMMSS.tar.gz
```

Uninstall:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/uninstall.sh
```

Das Uninstall-Skript stoppt und entfernt den systemd-Dienst, löscht aber die Daten nicht automatisch.

## CCV-Lagerterminal

Unter Einstellungen den ZVT Host `192.168.178.44` und Port `20007` eintragen,
CCV ZVT aktivieren, speichern und starten. Nach geaenderten Verbindungsdaten
einmal stoppen und wieder starten. Der Status unterscheidet Registrierung,
gesendete Anzeige und eine Antwort auf die Displayabfrage.

Die Integration verwendet den am CCV getesteten Ablauf `06 00` mit ACK und
Completion, danach `06 E1`. F1 entnimmt, F2 lagert ein, F3 zeigt Info, F4 Licht.
Im Mengendialog sind F1/F2 minus/plus, OK bucht, STOP bricht ab.
Die Bestandsbuchung verwendet die bestehende Part-DB- und stock_events-Logik.
Es werden nur Registrierung, Display/Input und Protokollbestaetigungen gesendet.

Die Hauptansicht zeigt Artikelname, Bestand des von der bestehenden Buchungslogik
verwendeten Lagerloses und Fachname. Das ist bei mehreren Lagerlosen nicht der
Gesamtbestand des Artikels. F3 aktualisiert die Detailansicht direkt; im Hauptmenue
werden die Daten spaetestens bei der naechsten Displayabfrage nach 15 Sekunden
neu geladen. Nicht abrufbare Bestaende erscheinen als `?`, nicht als Null.
Buchungsdialoge behalten den angezeigten Artikel; eine geaenderte oder abgelaufene
Scanauswahl verhindert die Buchung. Erfolg zeigt Menge und alten/neuen Bestand,
Testmodus und Fehler haben eigene Anzeigen. OK oder STOP schliesst das Ergebnis.

Echte Zahlentasten sind mit `06 E1` nicht implementiert: `31` bis `34` sind
Funktionstasten-Codes. Numerische Eingabe (`06 E2`) erfordert laut
[ZVT-Spezifikation, Kapitel 2.30](https://www.terminalhersteller.de/downloads/PA00P015_13.08_en.pdf)
eine Displaytext-MAC vom Hersteller und ist nicht freigeschaltet.

## Sicherheit

- Die Dienste sind für das lokale Heimnetz gedacht, nicht direkt für das Internet.
- Part-DB sollte hinter einem Reverse Proxy mit HTTPS liegen, wenn Zugriff von außerhalb nötig ist.
- `.env` enthält Secrets und gehört nicht in Git.
- Vor Updates immer ein Backup erstellen. Das Update-Skript macht das automatisch.
- WLED sollte im gleichen vertrauenswürdigen LAN bleiben.
- Für produktive Part-DB-Nutzung regelmäßig `data/partdb` sichern.
