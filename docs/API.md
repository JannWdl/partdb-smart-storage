# API

Die Smart-Storage-App stellt eine kleine JSON-API bereit.

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

Liefert Layout und berechnete Faecher inklusive LED-Bereichen.

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
        "serpentine": false,
        "slot_prefix": "Fach"
      }
    ]
  }
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

