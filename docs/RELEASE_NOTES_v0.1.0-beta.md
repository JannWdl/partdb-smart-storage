# v0.1.0-beta

Erste Beta von Part-DB Smart Storage.

## Enthalten

- Raspberry-Pi-Installer fuer Part-DB und Smart Storage.
- systemd-Service fuer Autostart des kompletten Docker-Compose-Stacks.
- FastAPI-Backend mit SQLite-Konfiguration.
- Visueller Setup-Assistent fuer Magazinlayout, Fachgroessen, LED-Bereiche und Serpentine.
- WLED-Anbindung fuer Locate/Test von Faechern.
- Part-DB-Suche und Teil-zu-Fach-Zuordnung.
- Barcode-Tab fuer USB-Scanner, manuelle Eingabe und Kamera-Scanner.
- Deutsche Tastaturkorrektur fuer Scanner, zum Beispiel `PARTÖ123` zu `PART:123`.
- Barcode-Aktionen `PART`, `DRAWER`, `ADD`, `REMOVE`, `WISHLIST`, `CANCEL`.
- Druckseiten fuer Grid-Uebersicht, Einzel-Etiketten und Aktionscodes.
- Backup, Restore, Update, Reload, Diagnose und Uninstall-Skripte.

## Beta-Hinweise

- Part-DBs REST-API ist upstream noch in Bewegung; Bestandsschreiben wird deshalb direkt versucht, auch wenn die OpenAPI-Doku nicht gelesen werden kann.
- Vor produktiver Nutzung Backups testen.
- WLED- und Magazinlayout sollten vor dem Etikettendruck einmal mit der Browser-Testseite geprueft werden.
