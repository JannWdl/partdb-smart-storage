# API

Die Smart-Storage-App stellt eine JSON-API per FastAPI bereit. Die automatische OpenAPI-Doku ist unter `/docs` erreichbar.

## Status

```http
GET /api/health
```

Antwort:

```json
{"ok": true, "partdb": true, "wled": true}
```

## Layout lesen

```http
GET /api/layout
```

Liefert Layout und berechnete Fächer inklusive LED-Bereichen.

## Layout speichern

```http
PUT /api/layout
Content-Type: application/json
```

```json
{
  "layout": {
    "name": "Mein Magazin",
    "cabinets": [
      {
        "id": "main",
        "name": "Hauptmagazin",
        "rows": 5,
        "columns": 4,
        "start_led": 0,
        "leds_per_slot": 4,
        "slot_width_mm": 55,
        "slot_height_mm": 38,
        "x": 24,
        "y": 24,
        "strip_path": "rows",
        "serpentine": false,
        "slot_prefix": "Fach"
      }
    ]
  }
}
```

## Einstellungen

```http
GET /api/settings
PUT /api/settings
```

```json
{
  "partdb_url": "http://partdb.local:8080",
  "partdb_internal_url": "http://partdb:80",
  "partdb_api_token": "",
  "wled_url": "http://192.168.178.220",
  "barcode_enabled": true,
  "barcode_camera_enabled": true,
  "scan_timeout_seconds": 30
}
```

## Fach testen

```http
POST /api/slots/main-1-1/locate
Content-Type: application/json
```

```json
{"mode": "locate"}
```

## WLED testen

```http
POST /api/wled/test
Content-Type: application/json
```

```json
{"wled_url": "http://192.168.178.220"}
```

## WLED-Zonen erzeugen und anwenden

```http
GET /api/wled/zones?mode=drawers
GET /api/wled/zones?mode=cabinets
POST /api/wled/apply-zones
```

```json
{
  "mode": "drawers",
  "brightness": 180
}
```

`drawers` erzeugt eine WLED-Zone pro Fach. `cabinets` erzeugt eine WLED-Zone pro Magazinblock.

## Teil suchen und Fach leuchten lassen

```http
GET /api/find?q=10k
```

## Part-DB durchsuchen

```http
GET /api/partdb/search?q=10k
```

## Zuordnung speichern

```http
POST /api/assignments
Content-Type: application/json
```

```json
{
  "part_id": "123",
  "part_name": "Widerstand 10k",
  "slot_id": "main-1-1",
  "notes": "R10K"
}
```

## Barcode-Scan

```http
POST /api/scan
Content-Type: application/json
```

```json
{"code": "PART:123"}
```

Unterstützte Codes: `PART:<partdb_id>`, `DRAWER:<drawer_id>`, `ADD`, `REMOVE`, `WISHLIST`, `CANCEL`.

## Lokale Bestandsbuchungen

```http
POST /api/stock/add
POST /api/stock/remove
GET /api/stock/events
```

Die Buchungen werden lokal protokolliert und verändern Part-DB-Bestände in v1 nicht direkt.
