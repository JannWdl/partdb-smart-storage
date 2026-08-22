# Backup und Sicherheit

## Was gesichert werden muss

Wichtig sind diese Pfade:

```text
/opt/partdb-smart-storage/.env
/opt/partdb-smart-storage/data/partdb
/opt/partdb-smart-storage/data/smart-storage
/opt/partdb-smart-storage/config
```

Das Backup-Skript packt genau diese Daten in ein Archiv unter:

```text
/opt/partdb-smart-storage/backups
```

## Backup automatisieren

Beispiel fuer einen taeglichen Cronjob:

```cron
15 3 * * * cd /opt/partdb-smart-storage && /opt/partdb-smart-storage/scripts/backup.sh
```

Kopiere Backups zusaetzlich auf ein NAS, eine externe SSD oder einen anderen Rechner.

## Sicherheit

- Keine Portweiterleitung direkt auf Part-DB oder Smart Storage.
- Zugriff nur im lokalen Netz oder ueber VPN.
- `.env` nicht veroeffentlichen.
- API-Token mit minimal notwendigen Rechten verwenden.
- Vor groesseren Aenderungen ein manuelles Backup erstellen.
- WLED und Raspberry Pi regelmaessig aktualisieren.

