# Part-DB Smart Storage

Reproduzierbares Raspberry-Pi-Projekt fuer Part-DB, WLED und ein visuelles Kleinteilemagazin.

Das Projekt entstand aus einer bestehenden Referenzinstallation auf Proxmox VM `120` (`partdb-wled`): Part-DB lief dort als Docker-Container auf Port `8080`, eine kleine Flask/WLED-Bridge auf Port `8090`, WLED war unter `192.168.178.220` erreichbar. Diese VM wurde nur gelesen und nicht veraendert.

## Funktionen

- Installiert Part-DB per Docker Compose auf Raspberry Pi OS 64-bit.
- Startet eine eigene Weboberflaeche auf Port `8090`.
- Konfiguriert Magazine visuell: Reihen, Spalten, Start-LED, LEDs pro Fach, Serpentine.
- Berechnet LED-Bereiche automatisch pro Fach.
- Speichert Teil-zu-Fach-Zuordnungen in einer eigenen SQLite-Datenbank.
- Sucht Teile in Part-DB, sofern die Part-DB-API erreichbar ist.
- Testet einzelne Faecher direkt am WLED-Controller.
- Bietet Locate-Suche: Teil suchen, passendes Fach leuchtet.
- Enthalt Install, Update, Backup, Restore und Uninstall.
- Laeuft nach Installation automatisch ueber systemd.

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
git clone https://github.com/DEINNAME/partdb-smart-storage.git
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

Wenn Part-DB ohne API-Token laeuft, kann die Smart-Storage-App trotzdem lokale Zuordnungen verwalten. Fuer echte Part-DB-Suche sollte in Part-DB ein API-Token erzeugt und als `PARTDB_API_TOKEN` eingetragen werden.

Nach Aenderungen:

```bash
cd /opt/partdb-smart-storage
docker compose up -d
```

## Magazinlayout

Das Standardlayout entspricht der Referenzidee:

- 5 Reihen
- 4 Spalten
- 4 LEDs pro kleinem Fach
- ein grosses Fach unten mit 16 LEDs
- insgesamt 96 LEDs

Das Layout kann in der Weboberflaeche geaendert werden. Intern liegt es unter:

```bash
/opt/partdb-smart-storage/data/smart-storage/layout.json
```

Eine Beispielkonfiguration liegt in `config/example-layout.json`.

## Bedienung

1. Part-DB oeffnen und Teile anlegen.
2. Smart Storage oeffnen.
3. Teil ueber die Part-DB-Suche suchen.
4. Fach auswaehlen.
5. `Speichern & testen` klicken.
6. Das Fach leuchtet am WLED-Controller.

Spaeter reicht die Suche oben links: Teilname eingeben, `Suchen & leuchten` klicken.

## Wartung

Update:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/update.sh
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

Das Uninstall-Skript stoppt und entfernt den systemd-Dienst, loescht aber die Daten nicht automatisch.

## Sicherheit

- Die Dienste sind fuer das lokale Heimnetz gedacht, nicht direkt fuer das Internet.
- Part-DB sollte hinter einem Reverse Proxy mit HTTPS liegen, wenn Zugriff von ausserhalb noetig ist.
- `.env` enthaelt Secrets und gehoert nicht in Git.
- Vor Updates immer ein Backup erstellen. Das Update-Skript macht das automatisch.
- WLED sollte im gleichen vertrauenswuerdigen LAN bleiben.
- Fuer produktive Part-DB-Nutzung regelmaessig `data/partdb` sichern.

## Referenzsystem

Gelesene Eckdaten der bestehenden Proxmox-Installation:

- Proxmox Host: `192.168.178.182`
- VM ID: `120`
- VM Name: `partdb-wled`
- VM IP: `192.168.178.221`
- OS: Debian GNU/Linux 13
- Compose-Datei: `/opt/partdb-wled/docker-compose.yml`
- Part-DB Image: `jbtronics/part-db1:latest`
- Part-DB Port: `8080`
- WLED-Bridge Port: `8090`
- WLED Ziel: `http://192.168.178.220`

Hinweis: Die Anfrage nannte CT/LXC `120`; auf dem Host ist `120` tatsaechlich eine QEMU-VM.

