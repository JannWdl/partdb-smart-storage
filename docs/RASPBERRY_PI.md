# Raspberry Pi Setup

Empfohlen:

- Raspberry Pi 4 oder neuer
- Raspberry Pi OS Lite 64-bit
- 8 GB RAM nicht erforderlich, 2 GB reichen fuer kleine Installationen
- LAN oder stabiles WLAN
- feste IP oder DHCP-Reservierung

## Vorbereitung

1. Raspberry Pi OS Lite 64-bit flashen.
2. SSH aktivieren.
3. Pi starten und einloggen.
4. System aktualisieren:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

## Installation

```bash
git clone https://github.com/DEINNAME/partdb-smart-storage.git
cd partdb-smart-storage
sudo ./scripts/install.sh
```

## WLED

Der WLED-Controller muss per HTTP erreichbar sein. Test:

```bash
curl http://192.168.178.220/json/info
```

Falls dein WLED eine andere IP hat, in `/opt/partdb-smart-storage/.env` anpassen:

```env
WLED_BASE_URL=http://DEINE-WLED-IP
```

## Autostart

Der Installer installiert einen systemd-Dienst fuer den kompletten Stack. Dieser startet beim Booten immer Part-DB und Smart Storage gemeinsam:

```bash
systemctl status partdb-smart-storage
```

Manuelle Steuerung:

```bash
sudo systemctl restart partdb-smart-storage
sudo systemctl stop partdb-smart-storage
sudo systemctl start partdb-smart-storage
```

Autostart reparieren oder nach einem Update neu setzen:

```bash
cd /opt/partdb-smart-storage
sudo ./scripts/ensure-autostart.sh
```

Container pruefen:

```bash
cd /opt/partdb-smart-storage
sudo docker compose ps
```
