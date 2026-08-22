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
APP_PORT=8090
PARTDB_PORT=8080
```

Wenn Part-DB ohne API-Token läuft, kann die Smart-Storage-App trotzdem lokale Zuordnungen verwalten. Für echte Part-DB-Suche sollte in Part-DB ein API-Token erzeugt und als `PARTDB_API_TOKEN` eingetragen werden.

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

## Wartung

Update:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/update.sh
```

Part-DB-Datenbankschema manuell aktualisieren:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/migrate-partdb.sh
```

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
