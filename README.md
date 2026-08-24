# Part-DB Smart Storage

Reproduzierbares Raspberry-Pi-Projekt für Part-DB, WLED und ein visuelles Kleinteilemagazin.

## Funktionen

- Installiert Part-DB per Docker Compose auf Raspberry Pi OS 64-bit.
- Startet eine eigene Weboberfläche auf Port `8090`.
- Konfiguriert Magazine visuell: Reihen, Spalten, Start-LED, LEDs pro Fach, Serpentine.
- Berechnet LED-Bereiche automatisch pro Fach.
- Speichert Teil-zu-Fach-Zuordnungen in einer eigenen SQLite-Datenbank.
- Sucht Teile in Part-DB, sofern die Part-DB-API erreichbar ist.
- Testet einzelne Fächer direkt am WLED-Controller.
- Verwaltet Part-DB-, WLED- und Barcode-Einstellungen in der Oberfläche.
- Unterstützt USB-Barcode-Scanner und Browser-Kamera-Scanner.
- Protokolliert lokale Bestandsbuchungen, ohne Part-DB-Bestände direkt zu verändern.
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

Das Barcode-Modul ist optional. Unterstützt werden USB-Scanner als Tastatureingabe und Browser-Kamera-Scanner, sofern der Browser `BarcodeDetector` unterstützt.

Standardcodes:

- `PART:<partdb_id>` wählt ein Teil.
- `DRAWER:<drawer_id>` wählt ein Fach.
- `ADD` bucht lokal Zugang.
- `REMOVE` bucht lokal Abgang.
- `WISHLIST` markiert lokal Nachkauf/Wunschliste.
- `CANCEL` beendet die aktuelle Scan-Session.

Die aktuelle Scan-Session läuft standardmäßig nach 30 Sekunden ab. Erfolg wird grün signalisiert, Fehler rot, Wunschliste blau und Locate gelb.

## WLED-Zonen

Die Oberfläche enthält einen WLED-Zonen Visual Creator. Er erzeugt aus dem aktuellen Magazinlayout automatisch WLED-Segmente:

- Modus `Fächer`: jedes Fach ist eine eigene Zone.
- Modus `Magazinblöcke`: jeder grafische Magazinblock ist eine Zone.
- Klick auf eine Zone testet den LED-Bereich direkt am Controller.
- `Zonen an WLED senden` schreibt die generierten Segmente in WLED.

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

## Sicherheit

- Die Dienste sind für das lokale Heimnetz gedacht, nicht direkt für das Internet.
- Part-DB sollte hinter einem Reverse Proxy mit HTTPS liegen, wenn Zugriff von außerhalb nötig ist.
- `.env` enthält Secrets und gehört nicht in Git.
- Vor Updates immer ein Backup erstellen. Das Update-Skript macht das automatisch.
- WLED sollte im gleichen vertrauenswürdigen LAN bleiben.
- Für produktive Part-DB-Nutzung regelmäßig `data/partdb` sichern.
