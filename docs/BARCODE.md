# Barcode-Modul

Das Barcode-Modul arbeitet optional und verändert Part-DB-Bestände in v1 nicht direkt. Es protokolliert lokale Buchungen in Smart Storage.

## Scanner-Arten

- USB-Scanner: funktioniert wie eine Tastatur. Fokus in das Scan-Feld setzen und scannen.
- Browser-Kamera: funktioniert, wenn der Browser `BarcodeDetector` unterstützt und Kamera-Zugriff erlaubt.

## Codes

- `PART:<partdb_id>` wählt ein Teil aus Part-DB.
- `DRAWER:<drawer_id>` wählt ein Fach.
- `ADD` bucht lokal Zugang.
- `REMOVE` bucht lokal Abgang.
- `WISHLIST` markiert lokal Nachkauf/Wunschliste.
- `CANCEL` beendet die aktuelle Scan-Session.

## Ablauf

1. `PART:<id>` scannen.
2. Optional `DRAWER:<drawer_id>` scannen, wenn das Teil noch keinem Fach zugeordnet ist.
3. `ADD`, `REMOVE` oder `WISHLIST` scannen.

Die Session läuft standardmäßig nach 30 Sekunden ab. Der Wert ist in der Oberfläche änderbar.

## Barcode-Bogen

`docs/barcode-sheet.html` im Browser öffnen und über den Druckdialog als PDF speichern.

