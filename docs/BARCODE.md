# Barcode-Modul

Das Barcode-Modul arbeitet optional. Wenn **Part-DB Bestand schreiben** aktiv ist, buchen `ADD` und `REMOVE` direkt in Part-DB und Smart Storage protokolliert das Ergebnis lokal. Wenn der Schalter aus ist, läuft der Barcode-Flow im lokalen Testmodus.

## Scanner-Arten

- USB-Scanner: funktioniert wie eine Tastatur. Fokus in das Scan-Feld setzen und scannen.
- Browser-Kamera: funktioniert, wenn der Browser `BarcodeDetector` unterstützt und Kamera-Zugriff erlaubt.

## Codes

- `PART:<partdb_id>` wählt ein Teil aus Part-DB.
- `DRAWER:<drawer_id>` wählt ein Fach.
- `ADD` bucht Zugang.
- `REMOVE` bucht Abgang.
- `WISHLIST` markiert lokal Nachkauf/Wunschliste.
- `CANCEL` beendet die aktuelle Scan-Session.

## Ablauf

1. `PART:<id>` oder `DRAWER:<drawer_id>` scannen.
2. Optional den zweiten Kontext scannen, wenn Teil und Fach bewusst kombiniert werden sollen.
3. `ADD`, `REMOVE` oder `WISHLIST` scannen.

Die Session läuft standardmäßig nach 30 Sekunden ab. Der Wert ist in der Oberfläche änderbar.

## Part-DB Bestand

In den Einstellungen:

- **Barcode aktiv** einschalten.
- **Part-DB Bestand schreiben** einschalten, wenn echte Bestandsänderungen gewünscht sind.
- **Part-DB Buchung testen** prüft API-Token und Part-DB-API.

Der API-Token braucht Rechte zum Lesen und Bearbeiten von Teilen/Lagerlosen. Wenn Part-DB die Buchung ablehnt oder nicht erreichbar ist, wird kein Erfolg angezeigt; die Buchung wird als `failed` protokolliert.

## Barcode-Bogen

In der Smart-Storage-Oberfläche gibt es den Tab **Drucken**.

- **Grid-Übersicht** druckt dein aktuelles Magazin-Layout mit Fach-Barcodes und den Aktionscodes für Plus, Minus, Nachkauf und Abbrechen.
- **Einzel-Etiketten** erzeugt je Fach ein eigenes Etikett für Etikettendrucker. Über **Einzeln drucken** kann genau ein Fach gedruckt werden.
- **Plus / Minus / Aktionen** druckt nur die Aktionscodes.

Die Druckseite erzeugt Code-128-Barcodes lokal im Browser und benötigt kein Internet.
